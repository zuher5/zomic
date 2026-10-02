"""Client webtoons.com (LINE Webtoon) versi Indonesia sebagai sumber data ketiga.

Bedanya dengan komiku_web.py / kiryuu_web.py: DAUN INI TIDAK menyapu HTML
katalog. Daftar episode diambil dari API JSON mobile yang terbuka:

    m.webtoons.com/api/v1/{webtoon|canvas}/{title_no}/episodes?pageSize=99999

Satu request mengembalikan seluruh katalog episode (ratusan), bukan satu
request per halaman. Ini yang membuat sumber ini jauh lebih murah dan stabil
daripada paginasi HTML.

Yang tetap di-scrape dari HTML (www.webtoons.com):
  - metadata series  : <title>/<h1 class="subj">, og:image, meta author
  - daftar gambar   : atribut data-url pada viewer episode

Dua jebakan yang sudah diuji dan wajib ditangani (lihat tests/):

1. Halaman viewer memuat ~335 URL `data-url`, tapi hanya sebagian kecil yang
   panel komik. Sisanya `thumb_*` (thumbnail pratinjau episode) dancona
   `*_warning.png` (lencana peringatan umur). Mengambil semuanya membuat
   reader menampilkan ratusan thumbnail sebelum panel pertama, dan gambar
   pertama adalah lencana — bukan isi komik.

2. Host CDN `webtoon-phinf` perlu ditulis ulang jadi `swebtoon-phinf` (HTTPS),
   dan query `?type=qN` dibuang supaya yang terunduh adalah varian kualitas
   asli. 헤 Referer dipasang walau hasil uji menunjukkan CDN sedang menerimanya
   tanpa Referer — biayanya nol, dan sebagian path CDNITIONS lebih ketat.

Semua parsing memakai stdlib (re + json) + requests, sama seperti modul lain.
"""

import html
import json
import os
import re
import threading
import time
from datetime import datetime
from urllib.parse import quote_plus, urlparse, parse_qs

import requests

SITE = "https://www.webtoons.com"
MOBILE = "https://m.webtoons.com"
LANG = "id"                 # lokalisasi Indonesia: /id/<genre>/<slug>/list
PER_PAGE = 24

RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.35

# CDN pstatic.net throttling keras: >5 pengambilan paralel dari satu host
# memicu 429. Satu chapter bisa 60+ panel dari host yang sama.
MIN_FETCH_INTERVAL = float(os.environ.get('WEBTOON_MIN_INTERVAL', '1.0'))
_FETCH_NEXT_FREE = {}
_FETCH_LOCK = threading.Lock()


def _throttle(url):
    """Jeda minimum per-host tanpa menahan lock saat tidur (pola kiryuu)."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return
    if not host:
        return
    now = time.monotonic()
    with _FETCH_LOCK:
        slot = _FETCH_NEXT_FREE.get(host, now)
        wait = slot - now
        _FETCH_NEXT_FREE[host] = max(now, slot) + MIN_FETCH_INTERVAL
    if wait > 0:
        time.sleep(wait)


def _retry_delay(resp, i, base_delay):
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


HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/json,*/*',
    'Accept-Language': 'id-ID,id;q=0.9,en;q=0.8',
    'Referer': SITE + '/',
}

# Age gate webtoons.com: tanpa cookie ini halaman dialihkan ke /ageGate, atau
# (lebih nasty) disajikan sebagai HTTP 200 berisi "Verify your age" — keduanya
# harus dideteksi.
AGE_GATE_COOKIES = {
    'ageGatePass': 'true',
    'needGDPR': 'false',
    'needCCPA': 'false',
    'needCOPPA': 'false',
    'pagGDPR': 'true',
    'atGDPR': 'AD_CONSENT',
    'locale': LANG,
}

_TAG = re.compile(r'<[^>]+>')
_TITLE_NO_RE = re.compile(r'\b(?:title_no|titleNo)=(\d+)')
# Link komik di halaman katalog: /id/<genre>/<slug>/list?title_no=N
_CARD_LINK_RE = re.compile(
    r'href="(?:https://www\.webtoons\.com)?/' + LANG +
    r'/([a-z0-9-]+)/([a-z0-9-]+)/list\?title_no=(\d+)[^"]*"', re.I)
# Aset UI yang tercampur di antara data-url panel.
_NOT_PANEL_RE = re.compile(r'(thumb_|warning|_logo|_icon|_btn|/btn)', re.I)
_IMG_DATAURL_RE = re.compile(r'data-url="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', re.I)
_CDN_QUALITY_RE = re.compile(r'[?&]type=q\d{1,3}\b', re.I)


def _text(raw):
    return re.sub(r'\s+', ' ', html.unescape(_TAG.sub(' ', raw or ''))).strip()


def _humanize_slug(s):
    """'how-to-win-my-husband-over' -> 'How To Win My Husband Over'."""
    return ' '.join(w.capitalize() for w in re.split(r'[-_]+', s or '') if w)


def _fix_cdn(url):
    """Host CDN -> HTTPS, buang ?type=qN agar dapat kualitas asli."""
    if not url:
        return None
    if url.startswith('//'):
        url = 'https:' + url
    url = url.replace('://webtoon-phinf.', '://swebtoon-phinf.')
    return _CDN_QUALITY_RE.sub('', url)


def _is_age_gate(resp, text=None):
    """Deteksi age gate yang disajikan sebagai 302 atau sebagai 200."""
    try:
        if '/ageGate' in (resp.url or ''):
            return True
    except Exception:
        pass
    if 'Verify your age' in (text or ''):
        return True
    return False


class WebtoonWeb:
    """Sumber data webtoons.com (LINE Webtoon) versi Indonesia."""

    def __init__(self, timeout=15):
        self.timeout = timeout

    # -- infra ---------------------------------------------------------
    def _session(self):
        s = requests.Session()
        s.headers.update(HEADERS)
        for k, v in AGE_GATE_COOKIES.items():
            try:
                s.cookies.set(k, v, domain='.webtoons.com')
            except Exception:
                s.cookies.set(k, v)
        return s

    def _fetch(self, url, timeout=None, attempts=None):
        session = self._session()
        kw = {'timeout': timeout or self.timeout}
        if attempts is not None:
            kw['attempts'] = attempts
        resp = retry_get(session, url, **kw)
        if resp is None:
            raise requests.RequestException(f'tidak ada respons: {url}')
        return resp

    # -- katalog -------------------------------------------------------
    @staticmethod
    def _parse_cards(raw, limit=PER_PAGE):
        """Kartu komik dari halaman katalog. Dedup per title_no."""
        out, seen = [], set()
        for m in _CARD_LINK_RE.finditer(raw or ''):
            genre, slug, tno = m.group(1), m.group(2), m.group(3)
            if tno in seen:
                continue
            seen.add(tno)
            chunk = (raw or '')[m.start():m.start() + 1200]
            img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', chunk)
            cover = _fix_cdn(img_m.group(1)) if img_m else ''
            alt_m = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', chunk)
            title = _text(alt_m.group(1)) if (alt_m and alt_m.group(1)) else _humanize_slug(slug)
            out.append({
                'title': title,
                'slug': slug,
                'title_no': int(tno),
                'type': 'webtoon',
                'genre': genre,
                'cover': cover,
                'url': f"{SITE}/{LANG}/{genre}/{slug}/list?title_no={tno}",
            })
            if len(out) >= limit:
                break
        return out

    def home(self, page=1):
        """Beranda /id/ — deretan komik untuk halaman depan."""
        try:
            raw = self._fetch(f"{SITE}/{LANG}/").text
        except requests.RequestException:
            return []
        return self._parse_cards(raw, limit=60)

    def popular(self):
        """Populer — LINE Webtoon tidak punya endpoint 'popular' terpisah,
        jadi pakai beranda yang sudah diurutkan kubut药水."""
        return self.home(1)

    def search(self, query, page=1):
        q = quote_plus(query or '')
        url = f"{SITE}/{LANG}/search?keyword={q}"
        if page > 1:
            url += f"&page={page}"
        try:
            raw = self._fetch(url).text
        except requests.RequestException:
            return []
        return self._parse_cards(raw)

    def by_genre(self, genre, page=1):
        url = f"{SITE}/{LANG}/genres/{genre}"
        try:
            raw = self._fetch(url).text
        except requests.RequestException:
            return []
        all_cards = self._parse_cards(raw, limit=999)
        start = (page - 1) * PER_PAGE
        return all_cards[start:start + PER_PAGE]

    def genres(self):
        """Genre diturunkan dari href katalog di beranda — stabil, karena
        genre webtoon jarang berubah dan tidak perlu endpoint khusus."""
        try:
            raw = self._fetch(f"{SITE}/{LANG}/").text
        except requests.RequestException:
            return []
        seen, out = set(), []
        for genre, _slug, _tno in _CARD_LINK_RE.findall(raw or ''):
            if genre in seen or genre == 'canvas':
                continue
            seen.add(genre)
            out.append({'slug': genre, 'name': _humanize_slug(genre)})
        return out

    # -- metadata & episode --------------------------------------------
    @staticmethod
    def _extract_title_no(url, raw=None):
        if raw:
            m = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', raw, re.I)
            if m:
                v = (parse_qs(urlparse(html.unescape(m.group(1))).query)
                     .get('title_no') or [None])[0]
                if v and v.isdigit():
                    return int(v)
        m = _TITLE_NO_RE.search(url or '')
        return int(m.group(1)) if m else None

    @staticmethod
    def _kind_from_url(url):
        """/id/canvas/<slug>/list -> canvas; selain itu webtoon."""
        parts = [p for p in (urlparse(url or '').path or '').split('/') if p]
        return 'canvas' if len(parts) >= 2 and parts[1].lower() == 'canvas' else 'webtoon'

    def detail(self, title_no, genre=None, slug=None):
        """Metadata series.

        URL series WAJIB memuat genre + slug (`/id/<genre>/<slug>/list?title_no=N`);
        `/id/list?title_no=N` tidak ada dan akan mengembalikan halaman kosong.
        Kalau genre/slug tidak diberi, dicoba cari lewat katalog beranda.
        """
        url = None
        if genre and slug:
            url = f"{SITE}/{LANG}/{genre}/{slug}/list?title_no={title_no}"
        else:
            try:
                for c in self.home(1):
                    if c.get('title_no') == int(title_no):
                        url = c.get('url')
                        break
            except Exception:
                pass
            if not url:
                url = f"{SITE}/{LANG}/x/y/list?title_no={title_no}"
        try:
            raw = self._fetch(url).text
        except requests.RequestException:
            return None
        return self._parse_detail(raw, title_no)

    @classmethod
    def _parse_detail(cls, raw, title_no):
        if not raw or '<title>Connect Error' in raw or '<title>404' in raw:
            return None
        tno = cls._extract_title_no(f"{SITE}/{LANG}/x/list?title_no={title_no}", raw) or title_no
        m = re.search(r'<h1[^>]*class="[^"]*subj[^"]*"[^>]*>(.*?)</h1>', raw, re.S)
        title = _text(m.group(1)) if m else ''
        cover = None
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', raw, re.I)
        if m:
            cover = _fix_cdn(m.group(1))
        if not title and not cover:
            return None
        author = None
        m = re.search(r'<meta[^>]+property="com-linewebtoon:webtoon:author"'
                      r'[^>]+content="([^"]+)"', raw, re.I)
        if m:
            author = _text(m.group(1))
        syn = None
        m = re.search(r'id="_asideDetail"[^>]*>.*?<p[^>]*class="[^"]*summary[^"]*"[^>]*>(.*?)</p>',
                      raw, re.S)
        if not m:
            m = re.search(r'<p[^>]*class="[^"]*summary[^"]*"[^>]*>(.*?)</p>', raw, re.S)
        if m:
            syn = _text(m.group(1))
        status = 'unknown'
        m = re.search(r'class="[^"]*day_info[^"]*"[^>]*>(.*?)</', raw, re.S)
        if m:
            dt = _text(m.group(1)).upper()
            if 'END' in dt or 'COMPLETED' in dt:
                status = 'completed'
            elif 'UP' in dt or 'EVERY' in dt:
                status = 'ongoing'
        genre = None
        m = re.search(r'<h2[^>]*class="[^"]*genre[^"]*"[^>]*>(.*?)</h2>', raw, re.S)
        if m:
            genre = _text(m.group(1))
        return {
            'title': title or f'Webtoon {tno}',
            'title_no': tno,
            'type': 'webtoon',
            'cover': cover,
            'author': author,
            'synopsis': syn,
            'status': status,
            'genre': genre,
            'url': f"{SITE}/{LANG}/list?title_no={tno}",
        }

    def episodes(self, title_no, kind='webtoon'):
        """Seluruh episode sebuah series dari API JSON mobile (1 request).

        Data di-embed di result.episodeList; `exposureDateMillis <= 0` berarti
        episode draft/belum tayang — dibuang.
        """
        url = f"{MOBILE}/api/v1/{kind}/{title_no}/episodes?pageSize=99999"
        try:
            resp = self._fetch(url, timeout=self.timeout + 5)
            data = resp.json()
        except (requests.RequestException, ValueError):
            return []
        result = data.get('result') or {}
        out = []
        for e in result.get('episodeList') or []:
            try:
                exp = int(e.get('exposureDateMillis') or 0)
            except (TypeError, ValueError):
                exp = 0
            if exp <= 0:
                continue          # draft / belum tayang
            try:
                no = int(e.get('episodeNo') or 0)
            except (TypeError, ValueError):
                continue
            if no <= 0:
                continue
            link = e.get('viewerLink') or ''
            if not link:
                continue
            d_str = ''
            if exp > 0:
                try:
                    d_str = datetime.fromtimestamp(exp / 1000).strftime('%d %b %Y')
                except Exception:
                    d_str = str(exp)
            out.append({
                'ch': str(no),
                'chapter': str(no),
                'title': e.get('episodeTitle') or f'Episode {no}',
                'url': link if link.startswith('http') else SITE + link,
                'date': d_str,
                'exposure_millis': exp,
                'has_bgm': bool(e.get('hasBgm')),
            })
        out.sort(key=lambda c: float(c['chapter']))
        return out

    def chapter_images(self, url_or_title_no, chapter=None):
        """URL panel dari halaman viewer, SUDAH dibersihkan.

        Bisa dipanggil dengan viewer URL langsung, atau (title_no, chapter).
        Hanya panel: buang `thumb_*`, `*_warning.png`, logo/icon/button, dan
        aset UI lain. Tanpa filter ini reader menampilkan ratusan thumbnail
        sebelum panel pertama.
        """
        if not url_or_title_no:
            return []
        url = url_or_title_no
        if chapter is not None or (isinstance(url_or_title_no, int) or str(url_or_title_no).isdigit()):
            eps = self.episodes(url_or_title_no)
            if not eps:
                eps = self.episodes(url_or_title_no, kind='canvas')
            ep = next((e for e in eps if str(e.get('ch', e.get('chapter', ''))) == str(chapter)), None)
            if not ep:
                return []
            url = ep.get('url')
        if not url:
            return []
        try:
            raw = self._fetch(url).text
        except requests.RequestException:
            return []
        if _is_age_gate(resp=None, text=raw):
            return []
        out, seen = [], set()
        for m in _IMG_DATAURL_RE.findall(raw):
            if _NOT_PANEL_RE.search(m):
                continue
            fixed = _fix_cdn(m)
            if fixed and fixed not in seen:
                seen.add(fixed)
                out.append(fixed)
        return out