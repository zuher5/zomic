"""Client REST API Sanka Vollerei (https://www.sankavollerei.web.id).

Membungkus tiga sumber komik yang REST-nya berjalan penuh:
softkomik, westmanga, komikstation. Tidak seperti kiryuu_web.py yang
scraping HTML, modul ini murni JSON — cukup normalisasi bentuk beda
tiga upstream ke satu kontrak bersama.

Dipakai requests + retry sederhana, timeout default 12 detik.
"""

import re
import threading
import time

import requests

BASE = "https://www.sankavollerei.web.id"
SOURCES = ('softkomik', 'westmanga', 'komikstation')

RETRY_STATUS = {429, 500, 502, 503, 504}
# 3x attempt: upstream kadang memutus koneksi seketika; retry instan
# murah dan menaikkan peluang sukses tanpa memperlambat gagalnya.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.35

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
    ),
    'Accept': 'application/json',
}

_TAG = re.compile(r'<[^>]+>')


def _strip_html(raw):
    """Westmanga menyisipkan <p> di sinopsis — buang tag-nya."""
    return re.sub(r'\s+', ' ', _TAG.sub(' ', str(raw or ''))).strip()


def _check_source(source):
    source = (source or '').strip().lower()
    if source not in SOURCES:
        raise ValueError(f"source harus salah satu dari {SOURCES}, dapat: {source!r}")
    return source


def _norm_status(raw):
    s = str(raw or '').strip().lower()
    if s in ('ongoing', 'berjalan', 'berlangsung', 'lanjut'):
        return 'Ongoing'
    if s in ('completed', 'complete', 'tamat', 'selesai', 'end', 'ended'):
        return 'Completed'
    return str(raw or '').strip()


def _genre_names(genres):
    """Genres tiap upstream beda bentuk: list[str] vs list[{name}]."""
    out = []
    for g in genres or []:
        if isinstance(g, str):
            out.append(g)
        elif isinstance(g, dict):
            name = g.get('name') or g.get('slug') or ''
            if name:
                out.append(name)
    return out


class SankaWeb:
    """REST client Sanka Vollerei. Semua method JSON-ready."""

    def __init__(self, timeout=12):
        self.timeout = timeout
        self._local = threading.local()

    def _session(self):
        try:
            return self._local.session
        except AttributeError:
            s = requests.Session()
            s.headers.update(HEADERS)
            self._local.session = s
            return s

    def _get(self, path, params=None, timeout=None):
        """GET JSON dengan retry terbatas untuk 429/5xx dan putus koneksi."""
        url = BASE + path
        for i in range(RETRY_ATTEMPTS):
            try:
                resp = self._session().get(
                    url, params=params, timeout=timeout or self.timeout,
                )
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ConnectTimeout,
                    requests.exceptions.ReadTimeout):
                if i == RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(RETRY_BASE_DELAY * (2 ** i))
                continue
            if resp.status_code in RETRY_STATUS and i < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BASE_DELAY * (2 ** i))
                continue
            resp.raise_for_status()
            return resp.json()
        return {}

    # ---------- latest ----------

    @staticmethod
    def _latest_items(source, body):
        # Tiap upstream menaruh daftar terbaru di tempat berbeda;
        # normalisasi ke satu titik supaya pemanggil cukup satu bentuk.
        if source == 'softkomik':
            data = body.get('data') or {}
            return data.get('latest') or data.get('latestUpdates') or []
        if source == 'westmanga':
            data = body.get('data')
            if isinstance(data, list):
                return data
            data = data or {}
            return data.get('mirror_update') or data.get('latest') or []
        # komikstation: tanpa wrapper "data"
        return body.get('latestUpdates') or (body.get('data') or {}).get('latestUpdates') or []

    @staticmethod
    def _latest_item(source, it):
        if source == 'softkomik':
            return {
                'title': it.get('title', ''),
                'slug': it.get('slug', ''),
                'cover': it.get('image', ''),
                'chapter': it.get('latestChapter', ''),
                'source': source,
            }
        if source == 'westmanga':
            last = (it.get('lastChapters') or [{}])[0]
            number = last.get('number', '')
            return {
                'title': it.get('title', ''),
                'slug': it.get('slug', ''),
                'cover': it.get('cover', ''),
                'chapter': str(number) if number else '',
                'source': source,
            }
        chapters = it.get('chapters') or []
        return {
            'title': it.get('title', ''),
            'slug': it.get('slug', ''),
            'cover': it.get('imageSrc', ''),
            'chapter': chapters[0].get('title', '') if chapters else '',
            'source': source,
        }

    def latest(self, source='softkomik', page=1):
        source = _check_source(source)
        page = max(1, int(page))
        # Endpoint home meneruskan ?page= (diabaikan hari ini), tapi
        # has_next hanya bisa dipercaya jika upstream mengirim metadata
        # paging — kalau tidak ada, anggap tidak ada halaman berikutnya.
        body = self._get(f"/comic/{source}/home", params={'page': page})
        items = [self._latest_item(source, it) for it in self._latest_items(source, body)]
        pagination = body.get('pagination') or {}
        has_next = bool(pagination.get('hasNext') or pagination.get('hasNextPage'))
        return {'items': items, 'page': page, 'has_next': has_next}

    # ---------- detail ----------

    def detail(self, source, slug):
        source = _check_source(source)
        slug = re.sub(r'[^a-z0-9\-]', '', (slug or '').lower())
        if not slug:
            raise ValueError("slug kosong")

        if source == 'softkomik':
            body = self._get(f"/comic/softkomik/detail/{slug}")
            d = body.get('data') or {}
            chapters = [
                {'title': c.get('title', ''), 'slug': c.get('slug', ''), 'date': c.get('date', '')}
                for c in d.get('chapters') or []
            ]
            rating = d.get('rating')
            if isinstance(rating, dict):
                rating = rating.get('average', '')
            return {
                'title': d.get('title', ''),
                'slug': d.get('slug', slug),
                'cover': d.get('image', ''),
                'status': _norm_status(d.get('status')),
                'type': d.get('type', ''),
                'author': d.get('author') or '',
                'rating': str(rating if rating is not None else ''),
                'synopsis': _strip_html(d.get('synopsis')),
                'genres': _genre_names(d.get('genres')),
                'chapters': list(reversed(chapters)),
                'source': source,
            }

        if source == 'westmanga':
            body = self._get(f"/comic/westmanga/detail/{slug}")
            d = body.get('data') or {}
            chapters = []
            for c in d.get('chapters') or []:
                number = c.get('number', '')
                chapters.append({
                    'title': f"Chapter {number}" if number else '',
                    'slug': c.get('slug', ''),
                    'date': (c.get('updated_at') or {}).get('formatted', ''),
                })
            return {
                'title': d.get('title', ''),
                'slug': d.get('slug', slug),
                'cover': d.get('cover', ''),
                'status': _norm_status(d.get('status')),
                'type': d.get('content_type', ''),
                'author': d.get('author', ''),
                'rating': str(d.get('rating', '') or ''),
                'synopsis': _strip_html(d.get('sinopsis')),
                'genres': _genre_names(d.get('genres')),
                # Upstream urut terbaru→terlama; balik supaya chapters[0]
                # chapter pertama — sama seperti komiku_web/kiryuu_web.
                'chapters': list(reversed(chapters)),
                'source': source,
            }

        # komikstation: response tanpa wrapper "data"
        body = self._get(f"/comic/komikstation/manga/{slug}")
        d = body.get('data') if isinstance(body.get('data'), dict) else body
        chapters = [
            {'title': c.get('title', ''), 'slug': c.get('slug', ''), 'date': c.get('date', '')}
            for c in d.get('chapters') or []
        ]
        return {
            'title': d.get('title', ''),
            'slug': d.get('slug') or slug,
            'cover': d.get('imageSrc', ''),
            'status': _norm_status(d.get('status') or d.get('Status')),
            'type': d.get('type', ''),
            'author': d.get('author', ''),
            'rating': str(d.get('rating', '') or ''),
            'synopsis': _strip_html(d.get('synopsis')),
            'genres': _genre_names(d.get('genres')),
            'chapters': list(reversed(chapters)),
            'source': source,
        }

    # ---------- chapter images ----------

    def chapter_images(self, source, comic_slug, chapter_slug):
        source = _check_source(source)
        chapter_slug = str(chapter_slug or '').strip()
        if not chapter_slug:
            return []

        if source == 'softkomik':
            # Softkomik wajib menyertakan slug komik di path chapter.
            comic_slug = re.sub(r'[^a-z0-9\-]', '', (comic_slug or '').lower())
            if not comic_slug:
                return []
            body = self._get(f"/comic/softkomik/chapter/{comic_slug}/{chapter_slug}")
        elif source == 'westmanga':
            body = self._get(f"/comic/westmanga/chapter/{chapter_slug}")
        else:
            body = self._get(f"/comic/komikstation/chapter/{chapter_slug}")

        node = body.get('data') if isinstance(body.get('data'), dict) else body
        images = node.get('images') or []
        if not images and source == 'softkomik':
            # Upstream kadang mengosongkan images saat CDN utama down;
            # imagesproxy tetap memuat halaman yang sama lewat proxy.
            images = node.get('imagesproxy') or []
        return images
