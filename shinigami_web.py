"""Native client untuk Shinigami-Api (Express.js + TypeScript).

Shinigami-Api adalah REST API scraping manga Shinigami (api.shngm.io)
yang berjalan sebagai service terpisah (default http://localhost:3001/api).
Modul ini memetakan responsnya ke kontrak item/detail Zomic:

- item:   {slug, title, cover, chapter, type, genre, status, rating, source}
- detail: {title, slug, alt_title, sinopsis, cover, genre, genres, type,
           status, author, rating, chapters:[{title, ch, date, url}],
           total_chapters, source}
- chapter images: list[str] URL gambar (diambil dari field imageUrl)

Namespace slug: ``shn-{manga_uuid}`` agar tidak tabrakan dengan slug
komiku/kiryuu/voratoon. Chapter diakses via UUID chapter Shinigami,
jadi ``chapter_images`` menerima slug ``shn-{uuid}`` + nomor chapter lalu
me-resolve nomor -> UUID lewat chapter list (di-cache per manga).
"""

import os
import re
import threading
import time

import requests

BASE = os.environ.get("SHINIGAMI_API_URL", "http://localhost:3001/api").rstrip("/")

RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.35

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Zomic/2.0 (+shinigami-adapter)",
}

# chapter "Chapter 921" / "Chapter 12 - Judul" -> "921" / "12"
_CH_NUM_RE = re.compile(r"chapter\s+([0-9]+(?:[.\-][0-9]+)?)", re.I)


def _chapter_num(name):
    m = _CH_NUM_RE.search(str(name or ""))
    return m.group(1) if m else ""


class ShinigamiWeb:
    """Client REST untuk Shinigami-Api dengan retry + chapter cache."""

    def __init__(self, base=None, timeout=20):
        self.base = (base or BASE).rstrip("/")
        self.timeout = timeout
        self._local = threading.local()
        self._chapters_cache = {}  # manga_uuid -> (ts, [chapter dicts])
        self._chapters_ttl = 1800

    def _session(self):
        try:
            return self._local.session
        except AttributeError:
            s = requests.Session()
            s.headers.update(HEADERS)
            self._local.session = s
            return s

    def _get_json(self, path, params=None, attempts=RETRY_ATTEMPTS):
        url = f"{self.base}{path}"
        last = None
        for i in range(attempts):
            try:
                resp = self._session().get(url, params=params, timeout=self.timeout)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ConnectTimeout,
                    requests.exceptions.ReadTimeout) as e:
                last = e
                if i == attempts - 1:
                    raise requests.RequestException(f"shinigami {url} gagal: {e}")
                time.sleep(RETRY_BASE_DELAY * (2 ** i))
                continue
            if resp.status_code in RETRY_STATUS and i < attempts - 1:
                time.sleep(RETRY_BASE_DELAY * (2 ** i))
                continue
            if resp.status_code == 404:
                raise requests.HTTPError("manga not found", response=resp)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as e:
                raise requests.RequestException(f"shinigami {url} bukan JSON: {e}")
        raise requests.RequestException(f"shinigami {url} gagal: {last}")

    # -- mapping --
    @staticmethod
    def _item(m):
        uuid = m.get("url") or ""
        return {
            "slug": f"shn-{uuid}" if uuid else "unknown",
            "raw_id": uuid,
            "title": m.get("title") or "Unknown",
            "cover": m.get("thumbnail") or "",
            "chapter": "",
            "type": "Manhwa",
            "genre": "",
            "status": "",
            "rating": "",
            "source": "shinigami",
        }

    @staticmethod
    def _strip_prefix(slug):
        s = str(slug or "").strip()
        return s[4:] if s.startswith("shn-") else s

    # -- public API (listing) --
    def _list(self, path, page=1, extra=None):
        try:
            params = {"page": page}
            if extra:
                params.update(extra)
            data = self._get_json(path, params=params)
        except requests.RequestException:
            return []
        payload = (data or {}).get("data") or {}
        return [self._item(m) for m in payload.get("mangas") or []]

    def latest(self, page=1):
        """Komik update terbaru (sort=latest di upstream)."""
        return self._list("/manga/latest", page)

    def popular(self):
        """Komik populer (sort=popularity di upstream)."""
        return self._list("/manga/popular", 1)

    def search(self, query, page=1):
        """Cari komik berdasar judul."""
        q = (query or "").strip()
        if not q:
            return {"items": [], "page": page, "per_page": 30,
                    "query": q, "has_next": False}
        try:
            data = self._get_json("/manga/search", params={"q": q, "page": page})
        except requests.RequestException:
            return {"items": [], "page": page, "per_page": 30,
                    "query": q, "has_next": False}
        payload = (data or {}).get("data") or {}
        return {
            "items": [self._item(m) for m in payload.get("mangas") or []],
            "page": page,
            "per_page": 30,
            "query": q,
            "has_next": bool(payload.get("hasNextPage")),
        }

    def by_genre(self, genre, page=1):
        """Shinigami-Api tidak punya endpoint genre -> search by keyword."""
        return self.search(genre, page)

    # -- detail --
    def _chapters(self, manga_uuid):
        now = time.time()
        hit = self._chapters_cache.get(manga_uuid)
        if hit and now - hit[0] < self._chapters_ttl:
            return hit[1]
        # Error upstream dilempar agar pemanggil bisa membedakan "kosong"
        # dari "gagal"; hasil gagal TIDAK di-cache.
        data = self._get_json(f"/manga/{manga_uuid}/chapters")
        raw = (data or {}).get("data") or []
        out = []
        for c in raw:
            num = _chapter_num(c.get("name"))
            if not num or not c.get("url"):
                continue
            out.append({
                "num": num,
                "uuid": c.get("url"),
                "title": c.get("name") or f"Chapter {num}",
            })
        self._chapters_cache[manga_uuid] = (now, out)
        return out

    def detail(self, slug):
        """Detail komik + daftar chapter (chapters diurut menaik)."""
        uuid = self._strip_prefix(slug)
        if not uuid:
            return None
        try:
            data = self._get_json(f"/manga/{uuid}")
        except requests.HTTPError as e:
            # Hanya 404 yang berarti "komik tidak ada". 5xx/403 = upstream
            # gagal; jangan disamarkan sebagai not-found.
            if e.response is not None and e.response.status_code == 404:
                return None
            raise
        except requests.RequestException:
            raise
        d = (data or {}).get("data")
        if not d:
            return None
        chapters = []
        for c in self._chapters(uuid):
            chapters.append({
                "title": c["title"],
                "ch": c["num"],
                "date": "",
                # url reader Zomic: /read/{slug}/{chapter-number}
                "url": f"/read/shn-{uuid}/{c['num']}",
            })

        def _key(c):
            try:
                return float(c["ch"])
            except (ValueError, TypeError):
                return 0.0

        chapters.sort(key=_key)
        genres = [g for g in str(d.get("genre") or "").split(",") if g.strip()]
        return {
            "title": d.get("title") or "Unknown",
            "slug": f"shn-{uuid}",
            "raw_id": uuid,
            "alt_title": "",
            "sinopsis": d.get("description") or "",
            "cover": d.get("thumbnail") or "",
            "genre": d.get("genre") or "",
            "genres": genres,
            "type": "Manhwa",
            "status": d.get("status") or "",
            "author": d.get("author") or "",
            "rating": "",
            "readers": "",
            "info": {
                "Author": d.get("author") or "",
                "Status": d.get("status") or "",
                "Type": "Manhwa",
            },
            "similar": [],
            "chapters": chapters,
            "total_chapters": len(chapters),
            "source": "shinigami",
        }

    def chapter_images(self, slug, chapter):
        """Resolve nomor chapter -> UUID lalu ambil daftar imageUrl."""
        uuid = self._strip_prefix(slug)
        ch = str(chapter or "").strip()
        if not uuid or not ch:
            return []
        target = None
        for c in self._chapters(uuid):
            if c["num"] == ch:
                target = c["uuid"]
                break
        if not target:
            # fallback: cocokkan float ("12" == "12.0")
            try:
                want = float(ch)
                for c in self._chapters(uuid):
                    try:
                        if float(c["num"]) == want:
                            target = c["uuid"]
                            break
                    except (ValueError, TypeError):
                        continue
            except (ValueError, TypeError):
                pass
        if not target:
            return []
        # Kegagalan upstream dilempar (bukan []), agar reader tidak menampilkan
        # "tidak ada halaman" saat sebenarnya Shinigami sedang down.
        data = self._get_json(f"/manga/chapter/{target}/pages")
        pages = (data or {}).get("data") or []
        return [p.get("imageUrl") for p in pages if p.get("imageUrl")]


shinigami = ShinigamiWeb()
