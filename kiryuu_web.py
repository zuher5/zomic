"""Client scraping HTML kiryuu.to sebagai sumber data kedua.

Kiryuu menggunakan WordPress Manga Stream (Miru Tensesi theme) dengan
struktur HTML yang konsisten. Modul ini mengekstrak katalog, pencarian,
genre, detail, dan gambar chapter langsung dari HTML kiryuu.to.

Sama seperti komiku_web.py, memakai stdlib (re + json) saja.
"""

import html
import json
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

SITE = "https://v7.kiryuu.to"
PER_PAGE = 24

RETRY_STATUS = {429, 500, 502, 503, 504}
# 3x attempt: lihat komentar yang sama di komiku_web.py.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.35

# Throttle per-host: kiryuu.to men-timeout request beruntun (anti-bot).
# Jaga jeda minimum antar request ke host yang sama supaya tidak kena blokir
# saat beberapa endpoint dipanggil bersamaan (burst). Bisa dioverride via env.
MIN_FETCH_INTERVAL = float(os.environ.get('KIRYUU_MIN_INTERVAL', '1.0'))
_FETCH_NEXT_FREE = {}          # host -> waktu paling awal request berikutnya
_FETCH_LOCK = threading.Lock()


def _throttle(url):
    """Jeda sesuai jadwal per-host TANPA menahan lock saat tidur.

    Versi lama melakukan sleep di dalam lock global: semua request (cross-host)
    ikut antre dan satu lock memblokir seluruh worker. Sekarang lock hanya
    dipakai sebentar untuk menjadwalkan, lalu sleep di luar lock sehingga
    request ke host lain tetap bisa jalan. Slot berikutnya di-reserve di dalam
    lock supaya burst tetap berurutan per host (tidak saling menabrak).
    """
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return
    if not host:
        return
    now = time.monotonic()
    with _FETCH_LOCK:
        # Slot berikutnya = slot yang sudah direserve, atau "sekarang" kalau
        # host belum pernah dipakai. M.reserve = max(M.kosong, M.slot + interval)
        # → thread yang datang bersamaan mendapat giliran, bukan jadwal sama.
        slot = _FETCH_NEXT_FREE.get(host, now)
        wait = slot - now
        _FETCH_NEXT_FREE[host] = max(now, slot) + MIN_FETCH_INTERVAL
    # Tidur DI LUAR lock supaya request ke host lain tidak terpengaruh.
    if wait > 0:
        time.sleep(wait)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'id-ID,id;q=0.9,en;q=0.8',
    'Referer': SITE + '/',
}


def _retry_delay(resp, i, base_delay):
    """Jeda sebelum attempt berikutnya: hormati Retry-After pada 429
    (cap 10 dtk), selain itu exponential backoff ringan."""
    if resp is not None and resp.status_code == 429:
        try:
            return min(max(float(resp.headers.get('Retry-After', '')), 0.0), 10.0)
        except (TypeError, ValueError):
            pass
    return base_delay * (2 ** i)


def retry_get(session, url, attempts=RETRY_ATTEMPTS, base_delay=RETRY_BASE_DELAY, **kwargs):
    for i in range(attempts):
        _throttle(url)
        try:
            resp = session.get(url, **kwargs)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout):
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))
            continue
        if resp.status_code in RETRY_STATUS and i < attempts - 1:
            time.sleep(_retry_delay(resp, i, base_delay))
            continue
        return resp
    return None


_TAG = re.compile(r'<[^>]+>')

def _text(raw):
    return re.sub(r'\s+', ' ', html.unescape(_TAG.sub(' ', raw or ''))).strip()

def _abs_url(url):
    if not url:
        return ''
    url = html.unescape(url.strip())
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        return SITE + url
    return url if url.startswith(('http://', 'https://')) else ''

def _rating_float(r):
    """Rating kartu (string) -> float; non-numerik/None -> 0.0."""
    try:
        return float(str(r or ''))
    except (TypeError, ValueError):
        return 0.0

def _humanize_slug(s):
    """Jadikan slug (mis. 'jungle-juice') tampil ramah: 'Jungle Juice'.

    Dipakai sebagai judul fallback bila HTML upstream tidak memuat judul asli.
    """
    return (s or '').replace('-', ' ').replace('_', ' ').strip().title()

def _clean_slug(href):
    """Ekstrak slug manga dari href kiryuu. /manga/{slug}/ → slug"""
    m = re.search(r'/manga/([a-z0-9\-]+)/', href or '')
    return m.group(1) if m else ''

def _clean_chapter_num(ch_num):
    """Bersihkan nomor chapter dari data-chapter-number.

    WordPress Manga Stream memakai float sebagai penanda urutan rilis:
    '3862.698726' artinya chapter 3862 yang rilis paling akhir — desimal
    panjang (>2 digit) adalah artefak pengurutan, bukan nomor chapter.
    Sebaliknya desimal pendek ('12.5') dan dash ('12-5') adalah nomor
    chapter asli dan dipertahankan apa adanya (jangan digabung: '12-5'
    bukan chapter 125, '12.5' bukan chapter 12).
    """
    ch_str = str(ch_num or '').strip()
    if '.' in ch_str:
        int_part, _, frac = ch_str.partition('.')
        frac_digits = re.sub(r'[^0-9]', '', frac)
        if len(frac_digits) > 2:
            return re.sub(r'[^0-9]', '', int_part)
        int_digits = re.sub(r'[^0-9]', '', int_part)
        return f"{int_digits}.{frac_digits}" if int_digits else frac_digits
    # Tanpa titik: pertahankan dash (chapter range ala '12-5').
    return re.sub(r'[^0-9\-]', '', ch_str).strip('-')


# --- Regex patterns untuk parsing ---

# Card listing: link ke manga + cover image.
# Host dibuat opsional (domain bisa bump v7->v8 / .to->.id, atau href relatif):
# grup 1 = href (absolut/relatif), grup 2 = slug. Nomor grup tidak berubah.
_CARD_LINK = re.compile(
    r'<a[^>]*href="((?:https?://[^"/]+)?/manga/([a-z0-9\-]+)/)"[^>]*>', re.I
)
_CARD_IMG = re.compile(
    r'<img[^>]*(?:src|data-src)="(https?://[^"]*?/wp-content/[^"]*)"[^>]*class="[^"]*wp-post-image',
    re.I
)
_CARD_IMG_FALLBACK = re.compile(
    r'<img[^>]*src="(https?://[^"]*?/wp-content/uploads/[^"]+)"', re.I
)
_CARD_TITLE_H1 = re.compile(
    r'<h1[^>]*class="[^"]*line-clamp-2[^"]*"[^>]*>\s*(.+?)\s*</h1>', re.S
)
_CARD_TITLE_H4 = re.compile(
    r'<h4[^>]*class="[^"]*line-clamp-2[^"]*"[^>]*>\s*(.+?)\s*</h4>', re.S
)
_CARD_RATING = re.compile(
    r'<div class="numscore">\s*([\d.]+)\s*</div>'
)
_CARD_TYPE = re.compile(
    r'(?:static/svg/|text-\[10px\][^>]*>\s*)(manga|manhwa|manhua)\b', re.I
)
_CHAPTER_URL = re.compile(
    r'href="((?:https?://[^"/]+)?/manga/[^/]+/chapter-([a-z0-9.\-]+)/)"', re.I
)
_CHAPTER_TIME = re.compile(
    r'<time[^>]*datetime="([^"]+)"', re.I
)
_PAGINATION = re.compile(
    r'href="[^"]*?\?page=(\d+)&pagedfor=(\w+)"'
)
_TOTAL_PAGES = re.compile(
    r'page=(\d+)&pagedfor="[^"]*"[^>]*>\s*(\d+)\s*</a>'
)

# Detail page patterns
def _find_series_jsonld(raw):
    """Temukan JSON-LD seri manga (Book/ComicSeries) di halaman detail.

    Daripada regex yang kaku pada urutan/@type tertentu, parse SEMUA blok
    application/ld+json lalu pilih yang @type-nya memuat Book atau ComicSeries.
    Header @type bisa array atau string tunggal; ketahanan ini membuatnya
    tahan jika upstream merombak format JSON-LD.
    """
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', raw, re.S):
        try:
            obj = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(obj, list):
            obj = next((o for o in obj if isinstance(o, dict)), None)
        if not isinstance(obj, dict):
            continue
        t = obj.get('@type', [])
        if isinstance(t, str):
            t = [t]
        if any(k in ('Book', 'ComicSeries', 'ComicIssue', 'CreativeWork') for k in t) and (obj.get('name') or obj.get('headline')):
            return obj
    return None
_GENRE_LINK = re.compile(
    r'itemprop="genre"\s+href="https://v7\.kiryuu\.to/genre/([a-z0-9\-]+)/"', re.I
)
_CHAPTER_LIST_ITEM = re.compile(
    r'<div\s+data-chapter-number="(\d+)"[^>]*>.*?href="(https://v7\.kiryuu\.to/manga/[^"]+/chapter-[^"]+)"',
    re.S
)
_CHAPTER_DATE = re.compile(
    r'<time[^>]*datetime="([^"]+)"[^>]*>\s*([^<]*)\s*</time>', re.I
)

# Chapter images: CDN bisa ganti host — terima host apa pun berekstensi gambar.
_CHAPTER_IMG_SECTION = re.compile(
    r'<section[^>]*data-image-data="1"[^>]*>(.*?)</section>', re.S
)
_CHAPTER_IMG = re.compile(
    r"""src=['"]?(https://[^'">\s]+\.(?:webp|jpe?g|png|gif|avif)(?:\?[^'">\s]*)?)['"]?""", re.I
)
_CHAPTER_IMG_FALLBACK = re.compile(
    r"""src=['"]?(https://[^'">\s]+/manga/[^'">\s]+\.(?:webp|jpe?g|png|gif|avif))['"]?""", re.I
)

# Genre index patterns (host opsional, grup tetap slug+nama)
_GENRE_FROM_PAGE = re.compile(
    r'href="(?:https?://[^"/]+)?/genre/([a-z0-9\-]+)/"[^>]*>\s*<span[^>]*>([^<]+)</span>',
    re.I
)


# AJAX search (htmx): POST admin-ajax.php?nonce=..&action=search dengan
# field 'query'. URL /?s=... tidak lagi mengembalikan hasil (title
# 'Advanced Search', 0 link manga) — search wajib lewat AJAX ini.
# Link manga diparse langsung dari blok (lihat _parse_ajax_results) supaya
# blok htmx yang tidak punya <h3> tetap tertangkap.
_AJAX_RESULT_TITLE = re.compile(r'<h3[^>]*>(.*?)</h3>', re.S | re.I)
_AJAX_RESULT_IMG = re.compile(r'<img[^>]*src="(https?://[^"]+)"', re.I)
_AJAX_SHOW_MORE = re.compile(r'advanced-search|show more', re.I)
# Nonce berubah-ubah tapi jarang; cache 10 menit agar tiap search tidak
# membayar satu request homepage tambahan.
NONCE_TTL = 600


class KiryuuWeb:
    """Scraper kiryuu.to. Semua method mengembalikan struktur JSON-ready."""

    def __init__(self, timeout=15):
        self.timeout = timeout
        self._local = threading.local()
        # Cache nonce bersama antar thread: satu request homepage cukup untuk
        # semua search yang arrive dalam window NONCE_TTL.
        self._nonce_lock = threading.Lock()
        self._nonce = ''
        self._nonce_exp = 0.0

    def _session(self):
        try:
            return self._local.session
        except AttributeError:
            s = requests.Session()
            s.headers.update(HEADERS)
            self._local.session = s
            return s

    def _fetch(self, url, timeout=None, attempts=None):
        resp = retry_get(
            self._session(), url,
            timeout=timeout or self.timeout,
            attempts=attempts or RETRY_ATTEMPTS,
        )
        resp.raise_for_status()
        return resp.text

    def _ajax_nonce(self):
        """Ambil nonce admin-ajax dari homepage (di-cache NONCE_TTL detik)."""
        now = time.monotonic()
        with self._nonce_lock:
            if self._nonce and now < self._nonce_exp:
                return self._nonce
        try:
            raw = self._fetch(SITE + '/', timeout=10, attempts=1)
        except requests.RequestException:
            return ''
        m = re.search(r'admin-ajax\.php\?nonce=([a-z0-9]+).*?action=search', raw)
        if not m:
            return ''
        nonce = m.group(1)
        with self._nonce_lock:
            self._nonce = nonce
            self._nonce_exp = time.monotonic() + NONCE_TTL
        return nonce

    @staticmethod
    def _parse_ajax_results(raw):
        """Parse hasil AJAX search (anchor /manga/{slug}/ + h3 + img).

        Skip anchor non-manja mis. 'Show more' -> /advanced-search/.
        Judul dari h3; bila kosong fallback humanize(slug).
        """
        items, seen = [], set()
        blocks = re.split(r'<a\s+href="', raw)
        for b in blocks[1:]:
            m = re.match(r'(?:https?://[^"/]+)?/manga/([a-z0-9\-]+)/"', b)
            if not m or m.group(1) in seen:
                continue
            slug = m.group(1)
            if _AJAX_SHOW_MORE.search(b[:400]):
                continue
            seen.add(slug)
            t = _AJAX_RESULT_TITLE.search(b)
            img = _AJAX_RESULT_IMG.search(b)
            items.append({
                'slug': slug,
                'title': html.unescape(_text(t.group(1))) if t else _humanize_slug(slug),
                'cover': html.unescape(img.group(1)) if img else '',
                'type': '', 'genre': '', 'status': '',
                'chapter': '', 'rating': '',
            })
        return items

    # ---------- parsing ----------

    @staticmethod
    def _parse_card_from_block(block):
        """Parse satu blok manga dari HTML block.

        Mencari link manga + cover image dari blok HTML.
        Return dict atau None.
        """
        link_m = _CARD_LINK.search(block)
        if not link_m:
            return None
        slug = link_m.group(2)
        if not slug or slug == 'unknown':
            return None

        # Cover image: cari wp-post-image dulu, fallback ke img biasa
        img_m = _CARD_IMG.search(block) or _CARD_IMG_FALLBACK.search(block)
        cover = img_m.group(1) if img_m else ''

        # Title: coba h1 dulu, lalu h4
        title_m = _CARD_TITLE_H1.search(block) or _CARD_TITLE_H4.search(block)
        title = _text(title_m.group(1)) if title_m else _humanize_slug(slug)

        # Rating
        rating_m = _CARD_RATING.search(block)
        rating = rating_m.group(1) if rating_m else ''

        # Type
        type_m = _CARD_TYPE.search(block)
        type_val = type_m.group(1).title() if type_m else ''

        # Chapter dari link chapter: pakai aturan yang sama dengan
        # _clean_chapter_num (desimal pendek & dash dipertahankan).
        ch_m = _CHAPTER_URL.search(block)
        chapter = ''
        if ch_m:
            chapter = _clean_chapter_num(ch_m.group(2))

        # Status
        status = ''
        if re.search(r'bg-green-600', block):
            status = 'Ongoing'
        elif re.search(r'bg-red-600|bg-orange', block):
            status = 'Completed'

        return {
            'slug': slug,
            'title': title,
            'cover': cover,
            'type': type_val,
            'genre': '',
            'status': status,
            'chapter': chapter,
            'rating': rating,
        }

    @classmethod
    def _parse_listing(cls, page):
        """Parse halaman listing manga (homepage, search results, dll).

        Cari blok-blok manga dalam page HTML. Kiryuu menggunakan
        struktur grid di dalam div project-list atau listupd.
        """
        items = []
        seen = set()

        # Strategi: cari semua link ke /manga/{slug}/ lalu parse blok di sekitarnya.
        # Karena HTML kiryuu cukup nested, kita pakai pendekatan robust:
        # 1. Cari semua link manga unik
        # 2. Untuk setiap slug, cari blok terkait

        # Simple approach: parse card berdasarkan struktur yang diketahui
        # Split page menjadi chunks berdasarkan card boundary

        # Cari semua manga links
        all_links = _CARD_LINK.findall(page)
        slug_order = []
        seen_slugs = set()
        for href, slug in all_links:
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                slug_order.append(slug)

        # Untuk setiap slug, cari blok konten di sekitar link
        for slug in slug_order:
            if slug in seen:
                continue
            seen.add(slug)

            # Cari posisi link ini di page untuk ambil konteks
            pattern = re.compile(
                re.escape(f'/manga/{slug}/'),
                re.I
            )
            m = pattern.search(page)
            if not m:
                continue

            # Ambil blok 2000 char setelah link
            start = max(0, m.start() - 500)
            end = min(len(page), m.end() + 2000)
            block = page[start:end]

            card = cls._parse_card_from_block(block)
            if card and card['slug'] == slug:
                items.append(card)

        return items

    @classmethod
    def _dedupe(cls, items):
        seen, out = set(), []
        for it in items:
            if it['slug'] not in seen:
                seen.add(it['slug'])
                out.append(it)
        return out

    # ---------- endpoint ----------

    def home(self, page=1):
        """Halaman utama: latest updates + trending."""
        page = max(1, int(page))
        url = f"{SITE}/?page={page}&pagedfor=project" if page > 1 else SITE
        raw = self._fetch(url)
        items = self._parse_listing(raw)
        items = self._dedupe(items)

        # Hitung total pages dari pagination
        pages_found = _PAGINATION.findall(raw)
        max_page = max([int(p) for p, _ in pages_found] + [page])

        return {
            'items': items,
            'page': page,
            'per_page': PER_PAGE,
            'total': max_page * PER_PAGE,
            'total_pages': max_page,
            'has_next': page < max_page,
        }

    def search(self, query, page=1):
        """Pencarian manga via AJAX admin-ajax (htmx): POST field 'query'.

        URL /?s={query} tidak lagi mengembalikan hasil (halaman 'Advanced
        Search' kosong) sehingga search wajib lewat endpoint AJAX ini.
        Endpoint upstream tidak punya pagination, tapi balutannya berisi
        daftar hasil lengkap (dibatasi max-h-96 di sisi htmx) — jadi
        pagination dilakukan di sini terhadap hasil yang sudah diterima,
        supaya page>1 tidak mengulang isi page 1.
        """
        query = (query or '').strip()
        if not query:
            return {'items': [], 'page': 1, 'per_page': PER_PAGE, 'query': '', 'has_next': False}
        page = max(1, int(page))
        nonce = self._ajax_nonce()
        if not nonce:
            return {'items': [], 'page': page, 'per_page': PER_PAGE,
                    'query': query, 'has_next': False}
        all_items = []
        url = f"{SITE}/wp-admin/admin-ajax.php?nonce={nonce}&action=search"
        for i in range(RETRY_ATTEMPTS):
            _throttle(url)
            try:
                resp = self._session().post(
                    url, data={'query': query}, timeout=self.timeout,
                    headers={'X-Requested-With': 'XMLHttpRequest'},
                )
                resp.raise_for_status()
                all_items = self._parse_ajax_results(resp.text)
                break
            except requests.RequestException:
                if i == RETRY_ATTEMPTS - 1:
                    all_items = []
                else:
                    time.sleep(RETRY_BASE_DELAY * (2 ** i))
        # Potong menjadi halaman PER_PAGE; total_pages dari jumlah hasil nyata.
        start = (page - 1) * PER_PAGE
        items = all_items[start:start + PER_PAGE]
        return {
            'items': items,
            'page': page,
            'per_page': PER_PAGE,
            'query': query,
            'total': len(all_items),
            'total_pages': max(1, -(-len(all_items) // PER_PAGE)),
            'has_next': start + PER_PAGE < len(all_items),
        }

    def by_genre(self, genre, page=1):
        """Manga berdasarkan genre."""
        genre = re.sub(r'[^a-z0-9\-]', '', (genre or '').lower())
        if not genre:
            return {'items': [], 'page': 1, 'per_page': PER_PAGE, 'genre': '', 'has_next': False}
        page = max(1, int(page))
        url = f"{SITE}/genre/{genre}/page/{page}/" if page > 1 else f"{SITE}/genre/{genre}/"
        try:
            raw = self._fetch(url)
        except requests.RequestException:
            return {'items': [], 'page': page, 'per_page': PER_PAGE, 'genre': genre, 'has_next': False}
        items = self._parse_listing(raw)
        items = self._dedupe(items)
        pages_found = _PAGINATION.findall(raw)
        max_page = max([int(p) for p, _ in pages_found] + [page])
        return {
            'items': items,
            'page': page,
            'per_page': PER_PAGE,
            'genre': genre,
            'has_next': page < max_page,
        }

    def genres(self):
        """Ambil daftar genre dari halaman kiryuu.

        Kiryuu embeds genre data sebagai JSON di script tag.
        Kita extract dari JSON tersebut.
        """
        try:
            raw = self._fetch(f"{SITE}/", timeout=15)
        except requests.RequestException:
            return []

        # Cari JSON genre data dari script
        m = re.search(r'var\s+searchTerms\s*=\s*(\{.*?"genre":\s*\[.*?\].*?\})', raw, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                genres = data.get('genre', [])
                return [{'slug': g['slug'], 'name': g['name']}
                        for g in genres if g.get('slug') and g.get('name')]
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: parse dari HTML links
        genres_m = _GENRE_FROM_PAGE.findall(raw)
        if genres_m:
            seen = set()
            out = []
            for slug, name in genres_m:
                if slug not in seen:
                    seen.add(slug)
                    out.append({'slug': slug, 'name': _text(name) or slug})
            return sorted(out, key=lambda g: g['name'].lower())

        return []

    def detail(self, slug):
        """Detail manga dari halaman kiryuu. Menggunakan JSON-LD."""
        slug = re.sub(r'[^a-z0-9\-]', '', (slug or '').lower())
        if not slug:
            raise ValueError("slug kosong")
        raw = self._fetch(f"{SITE}/manga/{slug}/")

        # Extract JSON-LD (Book/ComicSeries)
        ld = _find_series_jsonld(raw)
        if not ld:
            raise ValueError(f"JSON-LD tidak ditemukan untuk {slug}")

        # Cover dari JSON-LD image
        cover = ''
        img_obj = ld.get('image')
        if isinstance(img_obj, dict):
            cover = img_obj.get('url', '')
        elif isinstance(img_obj, str):
            cover = img_obj
        if not cover:
            og_m = re.search(r'<meta property="og:image" content="([^"]+)"', raw, re.I)
            if og_m:
                cover = og_m.group(1)

        # Title
        title = ld.get('name', '') or ld.get('headline', '') or _humanize_slug(slug)

        # Alt title
        alt_names = ld.get('alternateName', '')
        if isinstance(alt_names, list):
            alt_title = ', '.join(alt_names[:3])
        else:
            alt_title = str(alt_names)[:200]

        # Synopsis
        sinopsis = ld.get('description', '') or '-'
        sinopsis = html.unescape(sinopsis).strip()
        # Bersihkan [&hellip;] → ...
        sinopsis = sinopsis.replace('[&hellip;]', '...').replace('&hellip;', '...')

        # Genres
        genre = ld.get('genre', [])

        # Type / Status
        type_val = ld.get('creativeWorkStatus', '')
        status = 'Ongoing' if ld.get('isCompleted') is False else ('Completed' if ld.get('isCompleted') else '')

        # Rating
        agg = ld.get('aggregateRating') or {}
        rating = str(agg.get('ratingValue', ''))

        # Author
        author_obj = ld.get('author') or {}
        author = author_obj.get('name', '') if isinstance(author_obj, dict) else str(author_obj)

        # Total chapters dari numberOfPages (kiryuu pakai numberOfPages untuk chapter count)
        total_chapters = ld.get('numberOfPages', 0)

        # Parse chapter list dari HTML
        chapters = []
        ch_items = _CHAPTER_LIST_ITEM.findall(raw)
        seen_ch = set()
        for ch_num, _ch_href in ch_items:
            ch_clean = _clean_chapter_num(ch_num)
            if ch_clean and ch_clean not in seen_ch:
                seen_ch.add(ch_clean)
                # Cari tanggal dari blok sekitar
                ch_block_start = raw.find(f'data-chapter-number="{ch_num}"')
                time_str = ''
                if ch_block_start > 0:
                    ch_block = raw[ch_block_start:ch_block_start + 500]
                    date_m = _CHAPTER_DATE.search(ch_block)
                    if date_m:
                        time_str = _text(date_m.group(2))

                chapters.append({
                    'title': f"Chapter {ch_clean}",
                    'ch': ch_clean,
                    'date': time_str,
                })

        # Similar (rekomendasi) - halaman kiryuu tidak punya blok rekomendasi,
        # jadi selalu kosong; app.py mengisi dari listing se-genre untuk
        # halaman kiryuu-standalone.
        similar = []

        # HTML kiryuu urut newest-first; balik ke oldest-first agar kontrak
        # seragam dengan komiku (frontend: chapters[0] = chapter pertama
        # untuk "Start reading", display di-reverse saat "Latest first").
        chapters.reverse()

        return {
            'title': title,
            'slug': slug,
            'alt_title': alt_title,
            'sinopsis': sinopsis,
            'cover': cover,
            'genre': genre,
            'type': type_val,
            'status': status,
            'author': author,
            'rating': rating,
            'readers': '',
            'info': {
                'Author': author,
                'Status': status,
                'Tipe': type_val,
            },
            'similar': similar,
            'chapters': chapters,
            'total_chapters': len(chapters) or total_chapters,
        }

    def chapter_images(self, slug, chapter):
        """Ambil gambar chapter dari kiryuu.to.

        Chapter URL: /manga/{slug}/chapter-{chapter}.{id}/
        Gambar langsung di <section data-image-data="1"> tanpa lazy loading.
        """
        slug = re.sub(r'[^a-z0-9\-]', '', (slug or '').lower())
        chapter = re.sub(r'[^0-9.\-]', '', str(chapter or ''))
        if not slug or not chapter:
            return []

        # Coba URL langsung: /manga/{slug}/chapter-{chapter}/
        # kiryuu chapter URL membutuhkan ID, jadi kita perlu cari dari detail page
        # atau pakai search untuk menemukan chapter URL yang tepat.

        # Strategi: fetch detail page, cari chapter link yang match
        try:
            raw = self._fetch(f"{SITE}/manga/{slug}/", timeout=15)
        except requests.RequestException:
            return []

        # Cari chapter link untuk chapter ini
        ch_pattern = re.compile(
            rf'href="(https://v7\.kiryuu\.to/manga/{re.escape(slug)}/chapter-{re.escape(chapter)}\.[^"]+)"',
            re.I
        )
        ch_m = ch_pattern.search(raw)
        if not ch_m:
            # Coba tanpa ID: chapter-{chapter}/
            ch_pattern2 = re.compile(
                rf'href="(https://v7\.kiryuu\.to/manga/{re.escape(slug)}/chapter-{re.escape(chapter)}/)"',
                re.I
            )
            ch_m = ch_pattern2.search(raw)

        if not ch_m:
            return []

        chapter_url = ch_m.group(1)

        # Fetch chapter page
        try:
            ch_raw = self._fetch(chapter_url, timeout=20)
        except requests.RequestException:
            return []

        # Extract images dari <section data-image-data="1">
        section_m = _CHAPTER_IMG_SECTION.search(ch_raw)
        if section_m:
            images = _CHAPTER_IMG.findall(section_m.group(1))
            if images:
                return images

        # Fallback: cari semua yuucdn.com images di page
        images = _CHAPTER_IMG.findall(ch_raw)
        return images

    def popular(self):
        """Manga populer per tipe."""
        try:
            raw = self._fetch(f"{SITE}/manga/?order=popular", timeout=15)
        except requests.RequestException:
            raw = ''
        items = self._parse_listing(raw) if raw else []
        if not items:
            try:
                items = self.home(1).get('items', [])
            except requests.RequestException:
                items = []
            items = sorted(items, key=lambda c: _rating_float(c.get('rating')),
                           reverse=True)
        return self._dedupe(items)
