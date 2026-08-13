"""Client scraping HTML komiku.org untuk katalog penuh, pencarian, dan genre.

REST API pihak ketiga (api-komiku.vercel.app) hanya menyediakan 20 komik
terbaru dan endpoint /search-nya mengembalikan 500. Modul ini mengambil
langsung dari komiku.org supaya SEMUA komik (7.6rb+) bisa ditampilkan.

Sengaja memakai stdlib (re + html) agar tidak menambah dependensi seperti
BeautifulSoup, konsisten dengan modul scraper lain di proyek ini.
"""

import html
import re
import time
from urllib.parse import quote_plus

import requests

SITE = "https://komiku.org"
SEARCH_HOST = "https://api.komiku.org"
PER_PAGE_CATALOG = 50
PER_PAGE_SEARCH = 10

# Status yang boleh dicoba ulang karena gangguan upstream bersifat sementara.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.35


def retry_get(session, url, attempts=RETRY_ATTEMPTS, base_delay=RETRY_BASE_DELAY, **kwargs):
    """GET dengan retry terbatas + exponential backoff ringan.

    Hanya untuk request GET. Retry dilakukan pada status 429/5xx sementara dan
    error koneksi/read timeout; tidak pernah retry tanpa batas.
    """
    for i in range(attempts):
        try:
            resp = session.get(url, **kwargs)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout) as exc:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))
            continue
        if resp.status_code in RETRY_STATUS and i < attempts - 1:
            time.sleep(base_delay * (2 ** i))
            continue
        return resp

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'id-ID,id;q=0.9,en;q=0.8',
    'Referer': SITE + '/',
}

TYPES = ('manga', 'manhwa', 'manhua')

_CARD = re.compile(r'<article class="manga-card">(.*?)</article>', re.S)
_BGE = re.compile(r'<div class="bge">(.*?)<div class="kan">(.*?)</div>\s*</div>', re.S)
_SLUG = re.compile(r'href="(?:https?://komiku\.org)?/manga/([a-z0-9\-]+)/?"')
_IMG = re.compile(r'(?:data-src|src)="([^"]+)"')
_H4 = re.compile(r'<h4>\s*<a[^>]*>(.*?)</a>', re.S)
_H3 = re.compile(r'<h3>(.*?)</h3>', re.S)
_META = re.compile(r'<p class="meta">(.*?)</p>', re.S)
_TOTAL = re.compile(r'\(([\d.,]+)\s*komik\)')
_TYPE_INF = re.compile(r'<div class="tpe1_inf">\s*<b>([^<]*)</b>([^<]*)</div>', re.S)
_CHAP = re.compile(r'<span>(Awal|Terbaru):\s*</span>\s*<span>([^<]*)</span>', re.S)
_GENRE_LINK = re.compile(r'href="[^"]*?/genre/([a-z0-9\-]+)/?"[^>]*>([^<]{1,60})<')
_TAG = re.compile(r'<[^>]+>')


def _text(raw):
    """Bersihkan potongan HTML menjadi teks satu baris."""
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


def _is_placeholder(url):
    return 'asset/img/lazy' in url


# Snapshot daftar genre (slug, nama) dari komiku.org — dipakai sebagai cadangan
# bila situs menolak akses scraper (DDoS-Guard 403).
_GENRE_LINKS = (
    ('academy','Academy'),('action','Action'),('adaptation','Adaptation'),
    ('adult','Adult'),('adventure','Adventure'),('apocalypse','apocalypse'),
    ('beasts','Beasts'),('blacksmith','Blacksmith'),('businessman','Businessman'),
    ('comedy','Comedy'),('comic','Comic'),('cooking','Cooking'),('crime','Crime'),
    ('crossdressing','Crossdressing'),('dark-fantasy','Dark Fantasy'),
    ('demon','Demon'),('demons','Demons'),('doujinshi','Doujinshi'),
    ('drama','Drama'),('ecchi','Ecchi'),('entertainment','Entertainment'),
    ('fantasy','Fantasy'),('fight','Fight'),('furry','Furry'),('game','Game'),
    ('gender-bender','Gender Bender'),('genderswap','Genderswap'),('genius','Genius'),
    ('ghosts','Ghosts'),("girls-love","Girls' Love"),('gore','Gore'),('gyaru','Gyaru'),
    ('harem','Harem'),('hentai','Hentai'),('historical','Historical'),
    ('horror','Horror'),('isekai','Isekai'),('josei','Josei'),('kids','Kids'),
    ('knight','Knight'),('long-strip','Long Strip'),('magic','Magic'),
    ('magical-girls','Magical Girls'),('manga','Manga'),('mangatoon','Mangatoon'),
    ('manhwa','Manhwa'),('martial-art','Martial Art'),('martial-arts','Martial Arts'),
    ('mature','Mature'),('mc-rebirth','MC Rebirth'),('mecha','Mecha'),
    ('medical','Medical'),('military','Military'),('modern','Modern'),
    ('monster','Monster'),('monster-girls','Monster girls'),('monsters','Monsters'),
    ('murim','Murim'),('music','Music'),('mystery','Mystery'),('mythology','Mythology'),
    ('office-workers','Office Workers'),('one-shot','One Shot'),('oneshot','Oneshot'),
    ('police','Police'),('psychological','Psychological'),('regression','Regression'),
    ('reincarnation','Reincarnation'),('revenge','Revenge'),('reverse-harem','Reverse Harem'),
    ('romance','Romance'),('school','School'),('school-life','School life'),
    ('sci-fi','Sci-fi'),('seinen','Seinen'),('sexual-violence','Sexual Violence'),
    ('shotacon','Shotacon'),('shoujo','Shoujo'),('shoujo-ai','Shoujo Ai'),
    ('shoujog','Shoujo(G)'),('shounen','Shounen'),('shounen-ai','Shounen Ai'),
    ('slice-of-life','Slice of Life'),('slow-life','Slow Life'),('smut','Smut'),
    ('sport','Sport'),('sports','Sports'),('strategy','Strategy'),
    ('super-power','Super Power'),('supernatural','Supernatural'),('survival','Survival'),
    ('sword-fight','Sword Fight'),('sword-master','Sword Master'),('swormanship','Swormanship'),
    ('system','System'),('thriller','Thriller'),('time-travel','Time Travel'),
    ('tragedy','Tragedy'),('trauma','Trauma'),('vampire','Vampire'),
    ('video-games','Video Games'),('villainess','Villainess'),('violence','Violence'),
    ('web-comic','Web Comic'),('webtoon','Webtoon'),('webtoons','Webtoons'),
    ('xianxia','Xianxia'),('xuanhuan','Xuanhuan'),('yuri','Yuri'),
)


class KomikuWeb:
    """Scraper komiku.org. Semua method mengembalikan struktur JSON-ready."""

    def __init__(self, timeout=25):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _fetch(self, url):
        resp = retry_get(self.session, url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    # ---------- parsing ----------

    @staticmethod
    def _parse_total(page):
        m = _TOTAL.search(page)
        if not m:
            return None
        digits = re.sub(r'[^\d]', '', m.group(1))
        return int(digits) if digits else None

    @staticmethod
    def _parse_cards(page):
        """Parse grid <article class="manga-card"> pada /daftar-komik/."""
        items = []
        for block in _CARD.findall(page):
            slug_m = _SLUG.search(block)
            if not slug_m:
                continue
            covers = [_abs_url(u) for u in _IMG.findall(block)]
            cover = next((c for c in covers if c and not _is_placeholder(c)), '')
            title_m = _H4.search(block)
            meta = _text(_META.search(block).group(1) if _META.search(block) else '')
            ctype, genre, status = '', '', ''
            head = meta.split('Status:')
            if len(head) > 1:
                status = head[1].strip()
            parts = [p.strip() for p in head[0].split('•')]
            if parts:
                ctype = parts[0]
            if len(parts) > 1:
                genre = parts[1]
            items.append({
                'slug': slug_m.group(1),
                'title': _text(title_m.group(1)) if title_m else slug_m.group(1),
                'cover': cover,
                'type': ctype,
                'genre': genre,
                'status': status,
                'chapter': '',
            })
        return items

    @staticmethod
    def _parse_bge(page):
        """Parse listing <div class="bge"> pada hasil search/genre."""
        items = []
        for left, right in _BGE.findall(page):
            block = left + right
            slug_m = _SLUG.search(block)
            if not slug_m:
                continue
            covers = [_abs_url(u) for u in _IMG.findall(left)]
            cover = next((c for c in covers if c and not _is_placeholder(c)), '')
            title_m = _H3.search(right)
            tinf = _TYPE_INF.search(left)
            chapters = dict(_CHAP.findall(right))
            items.append({
                'slug': slug_m.group(1),
                'title': _text(title_m.group(1)) if title_m else slug_m.group(1),
                'cover': cover,
                'type': _text(tinf.group(1)) if tinf else '',
                'genre': _text(tinf.group(2)) if tinf else '',
                'status': '',
                'chapter': _text(chapters.get('Terbaru', '')),
            })
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

    def catalog(self, page=1, ctype=None, letter=None):
        """Katalog lengkap komiku.org (7.6rb+ komik), 50 per halaman."""
        params = [f"halaman={max(1, int(page))}"]
        if ctype and ctype.lower() in TYPES:
            params.append(f"tipe={ctype.lower()}")
        if letter:
            params.append(f"huruf={quote_plus(str(letter)[:1].upper())}")
        raw = self._fetch(f"{SITE}/daftar-komik/?{'&'.join(params)}")
        items = self._dedupe(self._parse_cards(raw))
        total = self._parse_total(raw)
        total_pages = max(1, -(-total // PER_PAGE_CATALOG)) if total else (page if items else 1)
        return {
            'items': items,
            'page': int(page),
            'per_page': PER_PAGE_CATALOG,
            'total': total,
            'total_pages': total_pages,
            'has_next': bool(items) and int(page) < total_pages,
            'filters': {'type': ctype or '', 'letter': (letter or '')[:1].upper()},
        }

    def search(self, query, page=1):
        """Pencarian judul di seluruh katalog (10 per halaman)."""
        query = (query or '').strip()
        if not query:
            return {'items': [], 'page': 1, 'per_page': PER_PAGE_SEARCH, 'query': '', 'has_next': False}
        page = max(1, int(page))
        url = f"{SEARCH_HOST}/page/{page}/?post_type=manga&s={quote_plus(query)}"
        items = self._dedupe(self._parse_bge(self._fetch(url)))
        return {
            'items': items,
            'page': page,
            'per_page': PER_PAGE_SEARCH,
            'query': query,
            'has_next': len(items) >= PER_PAGE_SEARCH,
        }

    def by_genre(self, genre, page=1):
        """Daftar komik per genre (10 per halaman)."""
        genre = re.sub(r'[^a-z0-9\-]', '', (genre or '').lower())
        if not genre:
            return {'items': [], 'page': 1, 'per_page': PER_PAGE_SEARCH, 'genre': '', 'has_next': False}
        page = max(1, int(page))
        url = f"{SEARCH_HOST}/page/{page}/?post_type=manga&s=&genre={genre}"
        items = self._dedupe(self._parse_bge(self._fetch(url)))
        return {
            'items': items,
            'page': page,
            'per_page': PER_PAGE_SEARCH,
            'genre': genre,
            'has_next': len(items) >= PER_PAGE_SEARCH,
        }

    def genres(self):
        """Daftar semua genre yang tersedia (~109 genre).

        komiku.org sekarang dilindungi DDoS-Guard dan sering menolak request
        scraper (403). Karena daftar genre praktis statis, kita pakai snapshot
        lokal sebagai cadangan bila fetch langsung gagal.
        """
        try:
            raw = self._fetch(f"{SITE}/genre/action/")
        except requests.RequestException:
            raw = ''
        out, seen = [], set()
        pairs = _GENRE_LINK.findall(raw) if raw else _GENRE_LINKS
        for slug, name in pairs:
            if slug in seen:
                continue
            seen.add(slug)
            label = _text(name) or slug.replace('-', ' ').title()
            out.append({'slug': slug, 'name': label})
        return sorted(out, key=lambda g: g['name'].lower())
