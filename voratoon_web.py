"""Client scraping VoraToon (https://v5.voratoon.com) — rebrand Komikcast.

Modul mandiri stdlib (re, html, json) + requests untuk katalog, pencarian,
ranking, detail komik, dan viewer chapter VoraToon.
"""

import html as html_lib
import json
import re
import threading
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests

BASE = "https://v5.voratoon.com"

# Status HTTP sementara yang boleh dicoba ulang.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.35

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/126.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/*,*/*;q=0.8',
    'Accept-Language': 'id-ID,id;q=0.9,en;q=0.8',
    'Referer': f"{BASE}/",
}

_ARTICLE_RE = re.compile(r'<article[\s\S]*?</article>', re.I)
_CHAPTER_PAGE_RE = re.compile(r'data-chapter-page="([^"]+)"')
_CHAPTER_ITEM_RE = re.compile(
    r'<a\s+class="chapter-item"\s+href="/series/[^/]+/chapter/([0-9.]+)">'
    r'[\s\S]*?chapter-number"[^>]*>([^<]*)<[\s\S]*?chapter-date"[^>]*>([^<]*)</',
    re.I
)
_TAG_CLEAN_RE = re.compile(r'<[^>]+>|<!--.*?-->')


def _clean_text(s):
    """Bersihkan teks HTML entitas dan whitespace."""
    if not s:
        return ''
    t = _TAG_CLEAN_RE.sub(' ', str(s))
    t = html_lib.unescape(t)
    return re.sub(r'\s+', ' ', t).strip()


def _humanize_slug(s):
    """Jadikan slug URL ramah baca: 'solo-leveling' -> 'Solo Leveling'."""
    return (s or '').replace('-', ' ').replace('_', ' ').strip().title()


def _fix_cover(url):
    """Pastikan cover URL absolut dan unescape ampersand."""
    if not url:
        return ''
    u = html_lib.unescape(url).strip()
    if u.startswith('/'):
        return f"{BASE}{u}"
    return u


def _retry_delay(resp, i, base_delay):
    """Exponential backoff dengan rasa hormat pada Retry-After."""
    if resp is not None and resp.status_code == 429:
        try:
            return min(max(float(resp.headers.get('Retry-After', '')), 0.0), 10.0)
        except (TypeError, ValueError):
            pass
    return base_delay * (2 ** i)


def retry_get(session, url, attempts=RETRY_ATTEMPTS, base_delay=RETRY_BASE_DELAY, **kwargs):
    """GET dengan retry terbatas + exponential backoff."""
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
            time.sleep(_retry_delay(resp, i, base_delay))
            continue
        return resp
    return None


class VoratoonWeb:
    """Scraper untuk v5.voratoon.com (REST & HTML)."""

    def __init__(self, timeout=20):
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
        if resp is None:
            raise requests.RequestException(f"tidak ada respons dari {url}")
        resp.raise_for_status()
        return resp.text

    # -- parsing katalog / latest --
    @staticmethod
    def _parse_latest_cards(html):
        """Parse kartu dari halaman /updates."""
        out, seen = [], set()
        articles = _ARTICLE_RE.findall(html or '')
        for a in articles:
            slug_m = re.search(r'href="/series/([a-z0-9-]+)"', a)
            if not slug_m:
                continue
            slug = slug_m.group(1)
            if slug in seen:
                continue
            seen.add(slug)

            title_m = (re.search(r'class="[^"]*update-series-card_title__[^"]*"[^>]*>([^<]+)<', a) or
                       re.search(r'alt="Cover ([^"]+)"', a))
            title = _clean_text(title_m.group(1)) if title_m else _humanize_slug(slug)

            cover_m = (re.search(r'<img[^>]*src="(/api/cover\?src=[^"]+)"', a) or
                       re.search(r'<img[^>]*src="([^"]+)"', a))
            cover = _fix_cover(cover_m.group(1)) if cover_m else ''

            ch_m = re.search(r'href="/series/[a-z0-9-]+/chapter/([0-9.]+)"', a)
            ch_num = ch_m.group(1) if ch_m else ''

            out.append({
                'slug': f"vt-{slug}",
                'raw_slug': slug,
                'title': title,
                'cover': cover,
                'chapter': f"Chapter {ch_num}" if ch_num else '',
                'type': 'Manhwa',
                'genre': '',
                'status': '',
                'rating': '',
                'source': 'voratoon',
            })
        return out

    # -- parsing pencarian / browse --
    @staticmethod
    def _parse_browse_cards(html):
        """Parse kartu dari halaman /browse."""
        out, seen = [], set()
        articles = _ARTICLE_RE.findall(html or '')
        for a in articles:
            t_m = re.search(r'<a class="card-title" href="/series/([a-z0-9-]+)">([^<]+)</a>', a)
            if not t_m:
                continue
            slug, title = t_m.group(1), _clean_text(t_m.group(2))
            if slug in seen:
                continue
            seen.add(slug)

            cover_m = (re.search(r'<img[^>]*src="(/api/cover\?src=[^"]+)"', a) or
                       re.search(r'<img[^>]*src="([^"]+)"[^>]*alt="[^"]*"', a))
            cover = _fix_cover(cover_m.group(1)) if cover_m else ''

            ch_m = re.search(r'tag-chapters"[^>]*>([^<]+)<', a)
            ch = _clean_text(ch_m.group(1)) if ch_m else ''

            st_m = re.search(r'data-status-tone="([a-z]+)"[^>]*>([^<]+)<', a)
            status = _clean_text(st_m.group(2)).title() if st_m else ''

            out.append({
                'slug': f"vt-{slug}",
                'raw_slug': slug,
                'title': title or _humanize_slug(slug),
                'cover': cover,
                'chapter': ch,
                'type': 'Manhwa',
                'genre': '',
                'status': status,
                'rating': '',
                'source': 'voratoon',
            })
        return out

    # -- parsing ranking / popular --
    @staticmethod
    def _parse_ranking_cards(html):
        """Parse kartu komik dari halaman /ranking."""
        out, seen = [], set()
        for m in re.finditer(r'<a\s+class="comic-row"\s+href="/series/([a-z0-9-]+)"[\s\S]*?</a>', html or '', re.I):
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            chunk = m.group(0)

            title_m = re.search(r'alt="Cover ([^"]+)"', chunk) or re.search(r'<h[1-5][^>]*>([^<]+)</h[1-5]>', chunk)
            title = _clean_text(title_m.group(1)) if title_m else _humanize_slug(slug)

            cover_m = (re.search(r'<img[^>]*src="(/api/cover\?src=[^"]+)"', chunk) or
                       re.search(r'<img[^>]*src="([^"]+)"', chunk))
            cover = _fix_cover(cover_m.group(1)) if cover_m else ''

            rating_m = re.search(r'class="comic-stars"[^>]*>[\s\S]*?<strong>([0-9.]+)</strong>', chunk)
            rating = rating_m.group(1) if rating_m else ''

            ch_m = re.search(r'Total\s*(?:<!--\s*-->)?\s*(\d+)\s*(?:<!--\s*-->)?\s*Chapters', chunk, re.I)
            chapter = f"Ch. {ch_m.group(1)}" if ch_m else ''

            out.append({
                'slug': f"vt-{slug}",
                'raw_slug': slug,
                'title': title,
                'cover': cover,
                'chapter': chapter,
                'type': 'Manhwa',
                'genre': '',
                'status': '',
                'rating': rating,
                'source': 'voratoon',
            })
        return out

    # -- public API --
    def latest(self, page=1):
        """Daftar komik rilis/update terbaru."""
        url = f"{BASE}/updates?page={page}" if page > 1 else f"{BASE}/updates"
        raw = self._fetch(url)
        return self._parse_latest_cards(raw)

    def search(self, query, page=1):
        """Cari komik berdasar judul/kata kunci."""
        q = (query or '').strip()
        if not q:
            return {'items': [], 'page': page, 'per_page': 30, 'query': q, 'has_next': False}
        url = f"{BASE}/browse?q={quote_plus(q)}&page={page}" if page > 1 else f"{BASE}/browse?q={quote_plus(q)}"
        raw = self._fetch(url)
        items = self._parse_browse_cards(raw)
        has_next = f"page={page + 1}" in (raw or '')
        return {'items': items, 'page': page, 'per_page': 30, 'query': q, 'has_next': has_next}

    def popular(self):
        """Daftar komik ranking / populer di Voratoon."""
        try:
            raw = self._fetch(f"{BASE}/ranking", attempts=2)
            return self._parse_ranking_cards(raw)
        except Exception:
            return []

    def by_genre(self, genre, page=1):
        """Daftar komik berdasarkan genre."""
        g = (genre or '').strip()
        url = f"{BASE}/browse?genre={quote_plus(g)}&page={page}" if page > 1 else f"{BASE}/browse?genre={quote_plus(g)}"
        raw = self._fetch(url)
        items = self._parse_browse_cards(raw)
        has_next = f"page={page + 1}" in (raw or '')
        return {'items': items, 'page': page, 'per_page': 30, 'genre': g, 'has_next': has_next}

    def detail(self, slug):
        """Detail komik + daftar episode/chapter lengkap."""
        raw_slug = str(slug or '').strip()
        if raw_slug.startswith('vt-'):
            raw_slug = raw_slug[3:]
        if not raw_slug:
            return None

        url = f"{BASE}/series/{raw_slug}"
        try:
            raw = self._fetch(url)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise

        if '<title>' in raw and ('404' in raw or 'not found' in raw.lower()) and 'chapter-item' not in raw:
            return None

        # 1. Parse JSON-LD ComicSeries
        meta = {}
        for ld in re.findall(r'<script type="application/ld\+json">([^<]+)</script>', raw):
            try:
                data = json.loads(ld)
                if isinstance(data, list) and data and data[0].get('@type') == 'ComicSeries':
                    meta = data[0]
                    break
            except Exception:
                continue

        title = _clean_text(meta.get('name'))
        if not title:
            h1_m = re.search(r'<h1[^>]*class="[^"]*series-title[^"]*"[^>]*>([^<]+)</h1>', raw, re.I)
            title = _clean_text(h1_m.group(1)) if h1_m else _humanize_slug(raw_slug)

        alt_title = _clean_text(meta.get('alternateName'))
        cover = _fix_cover(meta.get('image'))
        sinopsis = _clean_text(meta.get('description'))

        genres = meta.get('genre') or []
        if isinstance(genres, str):
            genres = [genres]
        genre_str = ", ".join(str(g).strip() for g in genres if str(g).strip())

        author = ''
        if isinstance(meta.get('author'), dict):
            author = _clean_text(meta['author'].get('name'))
        elif not author:
            auth_m = re.search(r'<span>✎ Author</span>\s*<strong[^>]*>([^<]+)</strong>', raw)
            if auth_m:
                author = _clean_text(auth_m.group(1))

        # 2. Status & Format (Type) dari info-grid HTML
        type_str = ''
        status_str = ''
        for m in re.finditer(r'<div class="info-item">\s*<span class="info-label">([^<]+)</span>\s*<strong[^>]*>(.*?)</strong>', raw, re.S):
            lbl = m.group(1).strip().lower()
            val = _clean_text(m.group(2))
            if 'format' in lbl or 'tipe' in lbl or 'type' in lbl:
                type_str = val.title()
            elif 'status' in lbl:
                status_str = val.title()

        # 3. Parse chapters
        chapters = []
        seen_ch = set()
        for m in _CHAPTER_ITEM_RE.finditer(raw):
            num = m.group(1)
            if num in seen_ch:
                continue
            seen_ch.add(num)
            raw_title = _clean_text(m.group(2))
            date = _clean_text(m.group(3))
            ch_title = f"Chapter {num}"
            if raw_title and raw_title.lower() != 'chapter':
                ch_title = f"Chapter {num} - {raw_title}"

            chapters.append({
                'title': ch_title,
                'ch': num,
                'date': date,
                'url': f"/read/vt-{raw_slug}/{num}",
            })

        # Urut menaik berdasar nomor float/int: Chapter 1 lebih dulu
        def _ch_key(c):
            try:
                return float(c['ch'])
            except (ValueError, TypeError):
                return 0.0

        chapters.sort(key=_ch_key)

        return {
            'title': title,
            'slug': f"vt-{raw_slug}",
            'raw_slug': raw_slug,
            'alt_title': alt_title or '',
            'sinopsis': sinopsis or '',
            'cover': cover,
            'genre': genre_str,
            'genres': [str(g).strip() for g in genres if str(g).strip()],
            'type': type_str,
            'status': status_str,
            'author': author,
            'rating': '',
            'readers': '',
            'info': {
                'Author': author,
                'Status': status_str,
                'Type': type_str,
            },
            'similar': [],
            'chapters': chapters,
            'total_chapters': len(chapters),
            'source': 'voratoon',
        }

    def chapter_images(self, slug, chapter):
        """Daftar URL gambar per panel dari chapter."""
        raw_slug = str(slug or '').strip()
        if raw_slug.startswith('vt-'):
            raw_slug = raw_slug[3:]
        ch = str(chapter or '').strip()
        if not raw_slug or not ch:
            return []

        url = f"{BASE}/series/{raw_slug}/chapter/{ch}"
        try:
            raw = self._fetch(url)
        except requests.RequestException:
            return []

        imgs, seen = [], set()
        for m in _CHAPTER_PAGE_RE.finditer(raw):
            img_url = html_lib.unescape(m.group(1)).strip()
            if img_url and img_url not in seen:
                seen.add(img_url)
                imgs.append(img_url)
        return imgs


voratoon = VoratoonWeb()
