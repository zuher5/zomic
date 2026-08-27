"""Client scraping HTML kiryuu.to sebagai sumber data kedua.

Kiryuu menggunakan WordPress Manga Stream (Miru Tensesi theme) dengan
struktur HTML yang konsisten. Modul ini mengekstrak katalog, pencarian,
genre, detail, dan gambar chapter langsung dari HTML kiryuu.to.

Sama seperti komiku_web.py, memakai stdlib (re + json) saja.
"""

import html
import json
import re
import threading
import time
from urllib.parse import quote_plus

import requests

SITE = "https://v7.kiryuu.to"
PER_PAGE = 24

RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.35

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'id-ID,id;q=0.9,en;q=0.8',
    'Referer': SITE + '/',
}


def retry_get(session, url, attempts=RETRY_ATTEMPTS, base_delay=RETRY_BASE_DELAY, **kwargs):
    for i in range(attempts):
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
            time.sleep(base_delay * (2 ** i))
            continue
        return resp


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

def _clean_slug(href):
    """Ekstrak slug manga dari href kiryuu. /manga/{slug}/ → slug"""
    m = re.search(r'/manga/([a-z0-9\-]+)/', href or '')
    return m.group(1) if m else ''

def _clean_chapter_num(ch_num):
    """Bersihkan nomor chapter: '3862' dari data-chapter-number."""
    ch_num = re.sub(r'[^0-9]', '', str(ch_num or ''))
    return ch_num


# --- Regex patterns untuk parsing ---

# Card listing: link ke manga + cover image
_CARD_LINK = re.compile(
    r'<a[^>]*href="(https://v7\.kiryuu\.to/manga/([a-z0-9\-]+)/)"[^>]*>', re.I
)
_CARD_IMG = re.compile(
    r'<img[^>]*(?:src|data-src)="([^"]*v7\.kiryuu\.to/wp-content/[^"]*)"[^>]*class="[^"]*wp-post-image',
    re.I
)
_CARD_IMG_FALLBACK = re.compile(
    r'<img[^>]*src="(https://v7\.kiryuu\.to/wp-content/uploads/[^"]+)"', re.I
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
    r'static/svg/(manga|manhwa|manhua)\.svg', re.I
)
_CHAPTER_URL = re.compile(
    r'href="(https://v7\.kiryuu\.to/manga/[^/]+/chapter-([a-z0-9.\-]+)/)"', re.I
)
_CHAPTER_TIME = re.compile(
    r'<time[^>]*datetime="([^"]+)"', re.I
)
_PAGINATION = re.compile(
    r'href="https://v7\.kiryuu\.to/\?page=(\d+)&pagedfor=(\w+)"'
)
_TOTAL_PAGES = re.compile(
    r'page=(\d+)&pagedfor="[^"]*"[^>]*>\s*(\d+)\s*</a>'
)

# Detail page patterns
_JSONLD = re.compile(
    r'<script type="application/ld\+json">\s*(\{[^<]*"@type"[^<]*\["?Book"?,\s*"?"ComicSeries"?\][^<]*\})\s*</script>',
    re.S
)
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

# Chapter images
_CHAPTER_IMG_SECTION = re.compile(
    r'<section[^>]*data-image-data="1"[^>]*>(.*?)</section>', re.S
)
_CHAPTER_IMG = re.compile(
    r"""src=['"]?(https://yuucdn\.com/[^'">\s]+)['"]?""", re.I
)
_CHAPTER_IMG_FALLBACK = re.compile(
    r"""src=['"]?(https://[^'">\s]+/manga/[^'">\s]+\.(?:webp|jpg|png))['"]?""", re.I
)

# Genre index patterns
_GENRE_FROM_PAGE = re.compile(
    r'href="https://v7\.kiryuu\.to/genre/([a-z0-9\-]+)/"[^>]*>\s*<span[^>]*>([^<]+)</span>',
    re.I
)


class KiryuuWeb:
    """Scraper kiryuu.to. Semua method mengembalikan struktur JSON-ready."""

    def __init__(self, timeout=25):
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

    def _fetch(self, url, timeout=None, attempts=None):
        resp = retry_get(
            self._session(), url,
            timeout=timeout or self.timeout,
            attempts=attempts or RETRY_ATTEMPTS,
        )
        resp.raise_for_status()
        return resp.text

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
        href, slug = link_m.group(1), link_m.group(2)
        if not slug or slug == 'unknown':
            return None

        # Cover image: cari wp-post-image dulu, fallback ke img biasa
        img_m = _CARD_IMG.search(block) or _CARD_IMG_FALLBACK.search(block)
        cover = img_m.group(1) if img_m else ''

        # Title: coba h1 dulu, lalu h4
        title_m = _CARD_TITLE_H1.search(block) or _CARD_TITLE_H4.search(block)
        title = _text(title_m.group(1)) if title_m else slug

        # Rating
        rating_m = _CARD_RATING.search(block)
        rating = rating_m.group(1) if rating_m else ''

        # Type
        type_m = _CARD_TYPE.search(block)
        type_val = type_m.group(1).title() if type_m else ''

        # Chapter dari link chapter: ambil angka utama saja (3862 dari 3862.698726)
        ch_m = _CHAPTER_URL.search(block)
        chapter = ''
        if ch_m:
            ch_slug = ch_m.group(2)
            ch_num_m = re.match(r'(\d+)', ch_slug)
            chapter = ch_num_m.group(1) if ch_num_m else ch_slug

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
        max_page = max([int(p) for _, p in pages_found] + [page])

        return {
            'items': items,
            'page': page,
            'per_page': PER_PAGE,
            'total': max_page * PER_PAGE,
            'total_pages': max_page,
            'has_next': page < max_page,
        }

    def search(self, query, page=1):
        """Pencarian manga. Kiryuu mendukung ?s={query}."""
        query = (query or '').strip()
        if not query:
            return {'items': [], 'page': 1, 'per_page': PER_PAGE, 'query': '', 'has_next': False}
        page = max(1, int(page))
        url = f"{SITE}/page/{page}/?s={quote_plus(query)}" if page > 1 else f"{SITE}/?s={quote_plus(query)}"
        raw = self._fetch(url)
        items = self._parse_listing(raw)
        items = self._dedupe(items)

        # Cek pagination untuk search
        pages_found = _PAGINATION.findall(raw)
        max_page = max([int(p) for _, p in pages_found] + [page])

        return {
            'items': items,
            'page': page,
            'per_page': PER_PAGE,
            'query': query,
            'has_next': page < max_page,
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
        max_page = max([int(p) for _, p in pages_found] + [page])
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
        ld_m = _JSONLD.search(raw)
        if not ld_m:
            raise ValueError(f"JSON-LD tidak ditemukan untuk {slug}")

        try:
            ld = json.loads(ld_m.group(1))
        except json.JSONDecodeError:
            raise ValueError(f"JSON-LD corrupt untuk {slug}")

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
        title = ld.get('name', '') or ld.get('headline', '') or slug

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
        for ch_num, ch_href in ch_items:
            ch_clean = _clean_chapter_num(ch_num)
            if ch_clean and ch_clean not in seen_ch:
                seen_ch.add(ch_clean)
                # Cari tanggal dari blok sekitar
                ch_block_start = raw.find(f'data-chapter-number="{ch_num}"')
                date_str = ''
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

        # Similar (rekomendasi) - cari section yang mirip
        similar = []

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
        """Manga populer via /manga/list-mode/?order=popular."""
        try:
            raw = self._fetch(f"{SITE}/manga/list-mode/?order=popular", timeout=15)
        except requests.RequestException:
            return []
        return self._parse_listing(raw)
