import json, re, os
import hashlib
import io
import tempfile
import threading
import time
from typing import List
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
import requests
from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from datetime import datetime, timedelta

from PIL import Image, features

from komiku_web import KomikuWeb, retry_get
from kiryuu_web import KiryuuWeb

# --- CACHE ---
cache = {}
def get_cache(key):
    if key in cache and cache[key]['exp'] > datetime.now():
        return cache[key]['data']
    return None

def get_stale_cache(key, max_age=21600):
    """Kembalikan data cache yang baru kedaluwarsa saat upstream sedang gagal."""
    item = cache.get(key)
    if not item:
        return None
    expired_for = datetime.now() - item['exp']
    if timedelta(0) <= expired_for <= timedelta(seconds=max_age):
        return item['data']
    return None
def set_cache(key, data, ttl=3600):
    cache[key] = {'data': data, 'exp': datetime.now() + timedelta(seconds=ttl)}

# Cache hasil resolver portrait: positif 7 hari (cover jarang berubah),
# negatif 1 hari (keputusan "portrait tidak ditemukan" tidak disimpan lama).
PORTRAIT_POS_TTL = 604800
PORTRAIT_NEG_TTL = 86400
# Paralelisme resolver portrait. Cukup kecil untuk tidak membebani upstream,
# cukup besar supaya listing besar (/rekomendasi ~40 item) selesai jauh di
# bawah batas 60s function Vercel saat cache dingin.
PORTRAIT_WORKERS = 8

# --- KOMIKU REST API CLIENT ---
class KomikuAPI:
    BASE = "https://api-komiku.vercel.app"
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36',
    }

    def __init__(self):
        self._local = threading.local()

    def _session(self):
        """Session per-thread: requests.Session tidak thread-safe, sedangkan
        resolver portrait berjalan di ThreadPoolExecutor yang berbagi instance
        ini antar thread. Session dibuat sekali per thread (pooling tetap ada).
        """
        try:
            return self._local.session
        except AttributeError:
            s = requests.Session()
            s.headers.update(self.HEADERS)
            self._local.session = s
            return s

    def _get(self, path, timeout=20):
        resp = retry_get(self._session(), f"{self.BASE}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def latest(self, page=1):
        try:
            data = self._get(f"/terbaru?page={page}")
        except Exception:
            data = self._get("/terbaru")
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            card = self._card(item)
            card['update'] = item.get('updateTime', '')
            card['colored'] = bool(item.get('isColored'))
            result.append(card)
        return self._resolve_portrait(result)

    def portrait_cover_api(self, slug):
        """Cover portrait via REST API upstream (/detail-komik).

        Jauh lebih andal daripada scraping halaman detail komiku.org yang
        dilindungi DDoS-Guard. Mengembalikan '' bila slug memang tidak punya
        cover portrait; error jaringan dilempar sebagai RequestException agar
        caller bisa membedakan "tidak ditemukan" vs "gagal sementara".
        """
        resp = retry_get(self._session(), f"{self.BASE}/detail-komik/{slug}",
                         attempts=1, timeout=5)
        if resp.status_code == 404:
            return ''
        resp.raise_for_status()
        try:
            d = resp.json()
        except ValueError:
            return ''
        cover = d.get('thumbnail') or ''
        if cover.startswith('//'):
            cover = 'https:' + cover
        if not cover.startswith(('http://', 'https://')):
            return ''
        low = cover.lower()
        # Tolak landscape: manga_img_horizontal atau resize W>H di query string.
        # Resize dicek SEBELUM query dibuang — setelah split('?') jadi dead code.
        if 'manga_img_horizontal' in low:
            return ''
        m = re.search(r'resize=(\d+),(\d+)', cover)
        if m and int(m.group(1)) > int(m.group(2)):
            return ''
        cover = cover.split('?')[0]  # buang param resize (?w=500) → source asli
        from urllib.parse import urlparse
        host = (urlparse(cover).hostname or '').lower()
        # Host dikenal (thumbnail.komiku.*, img.komiku.org) aman untuk semua
        # pola path: manga_thumbnail-*, img/upload/*, new/img/*.
        # Host lain ditolak karena tidak diverifikasi.
        if not any(kw in host for kw in ('thumbnail.komiku', 'img.komiku')):
            return ''
        return cover

    def detail(self, slug):
        d = self._get(f"/detail-komik/{slug}")
        cover = d.get('thumbnail') or ''
        if cover.startswith('//'):
            cover = 'https:' + cover
        chapters = []
        for ch in d.get('chapters', []):
            ch_num = ch.get('chapterNumber')
            if ch_num is None:
                m = re.search(r'chapter-(\d+(?:-\d+)?)', (ch.get('apiLink') or ''))
                ch_num = m.group(1) if m else ''
            chapters.append({
                'title': ch.get('title', f"Chapter {ch_num}"),
                'ch': str(ch_num),
                'date': ch.get('date', ''),
            })
        seen = set()
        chapters = [c for c in reversed(chapters) if not (c['ch'] in seen or seen.add(c['ch']))]

        info = d.get('info') or {}
        genre = d.get('genres') or []
        if not genre and info.get('Genre'):
            genre = [g for g in re.split(r'\s{2,}|,', info['Genre']) if g.strip()]

        similar = []
        for s in (d.get('similarKomik') or []):
            s_cover = s.get('thumbnail') or ''
            if s_cover.startswith('//'):
                s_cover = 'https:' + s_cover
            similar.append({
                'slug': s.get('slug') or (s.get('apiLink') or '').split('/')[-1],
                'title': s.get('title', ''),
                'cover': s_cover,
                'type': s.get('type', ''),
                'genre': s.get('genres', ''),
            })
        # Cover similar dari upstream sering banner/landscape (img/upload,
        # manga_img_horizontal) — resolve ke portrait kanonik seperti endpoint lain.
        if similar:
            similar = self._resolve_portrait(similar)

        return {
            'title': d.get('title', slug),
            'slug': d.get('slug') or slug,
            'alt_title': d.get('alternativeTitle') or info.get('Judul Alternatif', ''),
            'sinopsis': d.get('sinopsis') or d.get('description') or '-',
            'cover': cover,
            'genre': genre,
            'type': info.get('Tipe', ''),
            'status': info.get('Status', ''),
            'author': info.get('Author', ''),
            'rating': info.get('Rating', ''),
            'readers': info.get('Pembaca', ''),
            'info': info,
            'similar': similar,
            'chapters': chapters,
            'total_chapters': len(chapters),
        }

    @staticmethod
    def _card(item):
        """Normalisasi satu item listing dari REST API upstream."""
        cover = item.get('thumbnail') or ''
        if cover.startswith('//'):
            cover = 'https:' + cover
        slug = (
            item.get('mangaSlug')
            or item.get('slug')
            or (item.get('apiDetailLink') or item.get('detailUrl') or item.get('apiLink') or '').split('/')[-1]
        )
        genre = item.get('genre') or item.get('genres') or ''
        return {
            'title': item.get('title', 'Unknown'),
            'slug': slug or 'unknown',
            'cover': cover,
            'type': item.get('type', ''),
            'genre': genre if isinstance(genre, str) else ' '.join(genre),
            'status': '',
            'chapter': item.get('latestChapter') or item.get('latestChapterTitle') or '',
            'readers': item.get('readers') or item.get('views') or '',
        }

    def popular(self):
        """Komik populer, dikelompokkan per tipe (manga/manhwa/manhua)."""
        data = self._get("/komik-populer")
        groups = []
        if isinstance(data, dict):
            for key in ('manga', 'manhwa', 'manhua'):
                group = data.get(key)
                if not isinstance(group, dict):
                    continue
                items = [self._card(i) for i in (group.get('items') or [])]
                if items:
                    groups.append({'key': key, 'title': group.get('title', key.title()), 'items': self._resolve_portrait(items)})
        return groups

    def recommended(self):
        data = self._get("/rekomendasi")
        return self._resolve_portrait([self._card(i) for i in data]) if isinstance(data, list) else []

    def colored(self, page=1):
        """Komik berwarna. Upstream mengabaikan page, jadi selalu halaman 1."""
        data = self._get(f"/berwarna?page={page}")
        payload = data.get('data') if isinstance(data, dict) else None
        results = (payload or {}).get('results') if isinstance(payload, dict) else None
        items = [self._card(i) for i in results] if isinstance(results, list) else []
        return self._resolve_portrait(items)

    def billboard(self, limit=6):
        """Slide billboard dengan cover landscape ASLI (banner upstream).

        Endpoint listing lain me-resolve cover ke portrait 2:3 untuk grid kartu;
        billboard 16:9 justru butuh banner lebar (manga_img_horizontal /
        resize=450,235) agar tidak terpotong — jadi hasilnya sengaja TIDAK
        lewat _resolve_portrait. Sumber: /komik-populer di-round-robin antar
        tipe supaya tiap slide bervariasi, ditopup /rekomendasi mentah bila
        masih kurang dari `limit`.
        """
        seen, out = set(), []

        def push(card):
            slug = card.get('slug')
            cover = card.get('cover') or ''
            if not slug or slug == 'unknown' or slug in seen or len(out) >= limit:
                return
            if not cover.startswith(('http://', 'https://')):
                return
            seen.add(slug)
            out.append({k: card.get(k, '') for k in
                        ('slug', 'title', 'type', 'chapter', 'readers', 'genre', 'cover')})

        try:
            data = self._get("/komik-populer")
            groups = [data.get(k) for k in ('manga', 'manhwa', 'manhua')] if isinstance(data, dict) else []
            idx = 0
            progressed = True
            while progressed and len(out) < limit:
                progressed = False
                for g in groups:
                    items = (g or {}).get('items') or []
                    if idx < len(items):
                        progressed = True
                        push(self._card(items[idx]))
                idx += 1
        except requests.RequestException:
            pass  # populer gagal → coba top-up rekomendasi
        if len(out) < limit:
            try:
                data = self._get("/rekomendasi")
                for item in (data if isinstance(data, list) else []):
                    push(self._card(item))
                    if len(out) >= limit:
                        break
            except requests.RequestException:
                pass
        return out

    @staticmethod
    def _needs_portrait_resolution(card):
        """True hanya untuk cover yang perlu diganti ke portrait.

        Aturan:
        - Banner horizontal (manga_img_horizontal) → selalu landscape → resolve.
        - Query resize=W,H → W>H landscape crop → resolve; W<H portrait crop → aman.
        - Tanpa resize: manga_thumbnail di path → portrait resmi → aman; pola lain
          (new/img, img/upload, host lain) tidak dijamin portrait → resolve.
        """
        cover = card.get('cover') or ''
        if not cover or not card.get('slug'):
            return False
        path = cover.split('?')[0]
        if 'manga_img_horizontal' in path:
            return True
        m = re.search(r'resize=(\d+),(\d+)', cover)
        if m:
            return int(m.group(1)) > int(m.group(2))
        return 'manga_thumbnail' not in path

    def _resolve_portrait(self, items):
        """Ganti cover non-portrait (banner manga_img_horizontal, img/upload dll)
        dengan cover portrait manga_thumbnail dari halaman detail komiku.org,
        supaya pas di kotak 2:3. Hasil (termasuk keputusan "tidak ditemukan")
        di-cache sehingga fetch detail hanya terjadi saat cache dingin; kalau
        fetch gagal, cover lama dipertahankan dan dicoba lagi nanti.
        """
        if not items:
            return items

        def one(card):
            if not self._needs_portrait_resolution(card):
                return card
            key = f"portrait_{card['slug']}"
            hit = get_cache(key)
            if hit is not None:
                if hit:
                    card['cover'] = hit
                return card
            hit = ''
            try:
                # Sumber utama: REST API upstream (andal, tidak diblokir).
                hit = self.portrait_cover_api(card['slug']) or ''
            except requests.RequestException:
                # Fallback 1: scraping halaman detail komiku.org.
                try:
                    hit = web.portrait_cover(card['slug']) or ''
                except requests.RequestException:
                    # Fallback 2: kiryuu.to (cover WordPress portrait).
                    try:
                        hit = web.kiryuu_cover(card['slug']) or ''
                    except requests.RequestException:
                        return card
            set_cache(key, hit, ttl=PORTRAIT_POS_TTL if hit else PORTRAIT_NEG_TTL)
            if hit:
                card['cover'] = hit
            return card

        # Resolve tiap slug UNIK sekali saja: slug duplikat dalam satu listing
        # (umum di /rekomendasi & /populer) tidak boleh memicu panggilan ganda
        # saat cache dingin — hasilnya disalin ke semua duplikat sesudahnya.
        todo, first = [], set()
        for card in items:
            if self._needs_portrait_resolution(card) and card['slug'] not in first:
                first.add(card['slug'])
                todo.append(card)
        if not todo:
            return items
        try:
            with ThreadPoolExecutor(max_workers=PORTRAIT_WORKERS) as ex:
                list(ex.map(one, todo))
        except Exception:
            # Jangan sampai kegagalan resolve merusak listing: kembalikan apa adanya.
            return items
        resolved = {card['slug']: card['cover'] for card in todo}
        for card in items:
            if self._needs_portrait_resolution(card) and card['slug'] in resolved:
                card['cover'] = resolved[card['slug']]
        return items


    @staticmethod
    def _normalize_src(src):
        if not isinstance(src, str):
            return None
        src = src.strip()
        if not src:
            return None
        if src.startswith('//'):
            src = 'https:' + src
        return src if src.startswith(('http://', 'https://')) else None

    def _extract_images(self, data):
        """Ambil SEMUA gambar dari response, apa pun bentuk payload-nya."""
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ('images', 'chapterImages', 'pages', 'chapter_images', 'data'):
                value = data.get(key)
                if isinstance(value, list):
                    items = value
                    break

        collected = []
        for pos, item in enumerate(items):
            if isinstance(item, str):
                src, order = self._normalize_src(item), pos
            elif isinstance(item, dict):
                src = None
                for key in ('src', 'url', 'imageUrl', 'fallbackSrc'):
                    src = self._normalize_src(item.get(key))
                    if src:
                        break
                raw_id = str(item.get('id') or item.get('position') or '').strip()
                order = int(raw_id) if raw_id.isdigit() else pos
            else:
                continue
            if src:
                collected.append((order, pos, src))

        collected.sort(key=lambda t: (t[0], t[1]))
        seen, urls = set(), []
        for _, _, src in collected:
            if src not in seen:
                seen.add(src)
                urls.append(src)
        return urls

    def chapter(self, slug, chapter):
        data = self._get(f"/baca-chapter/{slug}/{chapter}")
        return self._extract_images(data)


api = KomikuAPI()
web = KomikuWeb()
kiryuu = KiryuuWeb()


def _merge_items(komiku_items, kiryuu_items):
    """Gabung listing komiku + kiryuu tanpa duplikat slug.

    Semua item komiku didahulukan (urutan ditentukan komiku). Item kiryuu
    yang slugnya belum ada di komiku ditambahkan di belakang. Setiap item
    mendapat key 'source' = 'komiku' | 'kiryuu' | 'both'.
    """
    seen = set()
    out = []
    for card in komiku_items:
        slug = card.get('slug')
        if slug and slug != 'unknown':
            seen.add(slug)
        card['source'] = 'komiku'
        out.append(card)
    for card in kiryuu_items:
        slug = card.get('slug')
        if not slug or slug in seen:
            # Slug sudah ada dari komiku → tandai sebagai 'both' pada item komiku
            if slug and slug in seen:
                for c in out:
                    if c.get('slug') == slug and c.get('source') == 'komiku':
                        c['source'] = 'both'
                        break
            continue
        seen.add(slug)
        card['source'] = 'kiryuu'
        out.append(card)
    return out

# --- FASTAPI APP ---
app = FastAPI(title="Zomic Komik", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def cached(key, producer, ttl=3600, stale_ttl=21600):
    """Gunakan cache fresh; saat upstream gagal, pakai cache stale yang masih baru."""
    hit = get_cache(key)
    if hit is not None:
        return hit
    try:
        data = producer()
    except requests.HTTPError as e:
        stale = get_stale_cache(key, stale_ttl)
        if stale is not None:
            return stale
        code = e.response.status_code if e.response is not None else 502
        raise HTTPException(status_code=404 if code == 404 else 502, detail=f"upstream {code}")
    except requests.RequestException:
        stale = get_stale_cache(key, stale_ttl)
        if stale is not None:
            return stale
        raise HTTPException(status_code=502, detail="upstream error")
    set_cache(key, data, ttl)
    return data


def _edge_cache(response: Response, s_maxage: int, browser: int = 60, swr: int | None = None):
    """Edge-cache respons di Vercel CDN untuk endpoint listing.

    s-maxage mengontrol umur di shared cache (CDN/edge); CDN-Cache-Control
    dipakai Vercel sebagai sumber kebenaran edge. stale-while-revalidate
    membuat CDN tetap melayani data lama sementara origin di-refresh.
    Browser memakai max-age kecil agar SPA tidak menahan data basi lama.
    """
    cc = f"public, max-age={browser}, s-maxage={s_maxage}"
    cdn = f"public, s-maxage={s_maxage}"
    if swr:
        cc += f", stale-while-revalidate={swr}"
        cdn += f", stale-while-revalidate={swr}"
    response.headers['Cache-Control'] = cc
    response.headers['CDN-Cache-Control'] = cdn


@app.get("/api/latest")
def latest(page: int = Query(1, ge=1), response: Response = None):
    def _latest():
        komiku_data = api.latest(page)
        try:
            kiryuu_data = kiryuu.home(page).get('items', [])
        except Exception:
            kiryuu_data = []
        return _merge_items(komiku_data, kiryuu_data)

    data = cached(f"latest_{page}", _latest, ttl=600)
    _edge_cache(response, s_maxage=300, swr=900)
    return data

@app.get("/api/catalog")
def catalog(
    page: int = Query(1, ge=1, le=200),
    type: str = Query("", pattern=r'^(manga|manhwa|manhua)?$'),
    letter: str = Query("", max_length=1),
    response: Response = None,
):
    """Katalog LENGKAP komiku.org (7.6rb+ komik), 50 per halaman."""
    key = f"catalog_{page}_{type}_{letter}"

    def _catalog():
        data = web.catalog(page, ctype=type or None, letter=letter or None)
        data['items'] = api._resolve_portrait(data['items'])
        return data

    data = cached(key, _catalog, ttl=1800)
    _edge_cache(response, s_maxage=900, swr=3600)
    return data

@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=100), page: int = Query(1, ge=1, le=100),
           response: Response = None):
    """Pencarian di seluruh katalog, bukan hanya 20 komik terbaru."""
    def _search():
        komiku_data = web.search(q, page)
        komiku_data['items'] = api._resolve_portrait(komiku_data['items'])
        try:
            kiryuu_res = kiryuu.search(q, page)
            kiryuu_items = kiryuu_res.get('items', [])
        except Exception:
            kiryuu_items = []
        komiku_data['items'] = _merge_items(komiku_data['items'], kiryuu_items)
        return komiku_data

    data = cached(f"search_{q.lower()}_{page}", _search, ttl=900)
    _edge_cache(response, s_maxage=300, swr=900)
    return data

@app.get("/api/genres")
def genres(response: Response = None):
    def _genres():
        komiku_genres = web.genres()
        try:
            kiryuu_genres = kiryuu.genres()
        except Exception:
            kiryuu_genres = []
        # Merge genre lists by slug; prefer komiku names, add kiryuu-unique
        seen = set()
        out = []
        for g in komiku_genres:
            seen.add(g['slug'])
            out.append(g)
        for g in kiryuu_genres:
            if g['slug'] not in seen:
                seen.add(g['slug'])
                out.append(g)
        return out

    data = cached("genres", _genres, ttl=86400)
    _edge_cache(response, s_maxage=86400, swr=86400, browser=900)
    return data

@app.get("/api/genre/{slug}")
def genre_detail(slug: str, page: int = Query(1, ge=1, le=100), response: Response = None):
    def _genre():
        komiku_data = web.by_genre(slug, page)
        komiku_data['items'] = api._resolve_portrait(komiku_data['items'])
        try:
            kiryuu_data = kiryuu.by_genre(slug, page)
            kiryuu_items = kiryuu_data.get('items', [])
            # Merge pagination: gunakan max total_pages dari kedua sumber
            kiryuu_data_max = kiryuu_data.get('total_pages', 0)
            if kiryuu_data_max > komiku_data.get('total_pages', 0):
                komiku_data['total_pages'] = kiryuu_data_max
                komiku_data['has_next'] = kiryuu_data.get('has_next', False)
        except Exception:
            kiryuu_items = []
        komiku_data['items'] = _merge_items(komiku_data['items'], kiryuu_items)
        return komiku_data

    data = cached(f"genre_{slug}_{page}", _genre, ttl=1800)
    if not data['items'] and page == 1:
        raise HTTPException(status_code=404, detail="genre tidak ditemukan")
    _edge_cache(response, s_maxage=600, swr=1800)
    return data

@app.get("/api/popular")
def popular(response: Response = None):
    def _popular():
        komiku_groups = api.popular()
        try:
            kiryuu_pop = kiryuu.popular()
        except Exception:
            kiryuu_pop = []
        if kiryuu_pop:
            # Merge kiryuu popular ke setiap grup komiku berdasarkan type
            for group in komiku_groups:
                k_type = group['key']
                matching = [c for c in kiryuu_pop if c.get('type', '').lower() == k_type]
                if matching:
                    group['items'] = _merge_items(group['items'], matching)
        return komiku_groups

    data = cached("popular", _popular, ttl=3600)
    _edge_cache(response, s_maxage=600, swr=3600)
    return data

@app.get("/api/recommended")
def recommended(response: Response = None):
    def _recommended():
        komiku_items = api.recommended()
        # kiryuu tidak punya /recommended, tapi kita bisa ambil dari home()
        try:
            kiryuu_items = kiryuu.home(1).get('items', [])[:20]
        except Exception:
            kiryuu_items = []
        return _merge_items(komiku_items, kiryuu_items)

    data = cached("recommended", _recommended, ttl=3600)
    _edge_cache(response, s_maxage=600, swr=3600)
    return data

@app.get("/api/billboard")
def billboard(response: Response = None):
    """Slide hero: cover landscape asli upstream, tanpa resolve portrait.
    Termasuk item kiryuu dari /popular.
    """
    def _billboard():
        komiku_bill = api.billboard()
        # Tambah item kiryuu populer sebagai billboard slide
        try:
            kiryuu_pop = kiryuu.popular()[:10]
            for item in kiryuu_pop:
                item['source'] = 'kiryuu'
                # billboard memakai slug sebagai dedupe key
            # Dedupe by slug, append kiryuu items yang belum ada
            komiku_slugs = {i.get('slug') for i in komiku_bill}
            for item in kiryuu_pop:
                if item.get('slug') and item['slug'] not in komiku_slugs:
                    komiku_bill.append(item)
                    komiku_slugs.add(item['slug'])
        except Exception:
            pass
        return komiku_bill

    data = cached("billboard", _billboard, ttl=3600)
    _edge_cache(response, s_maxage=600, swr=3600)
    return data

@app.get("/api/colored")
def colored(response: Response = None):
    def _colored():
        komiku_items = api.colored()
        # kiryuu tidak punya endpoint berwarna, tapi kita bisa ambil dari home()
        # yang sudah diurutkan berdasarkan update terbaru
        return komiku_items

    data = cached("colored", _colored, ttl=1800)
    _edge_cache(response, s_maxage=600, swr=1800)
    return data

@app.get("/api/detail/{slug}")
def detail(slug: str, response: Response = None):
    def _detail():
        komiku_d = api.detail(slug)
        # Merge kiryuu detail jika tersedia
        try:
            kiryuu_d = kiryuu.detail(slug)
            # Ambil chapter dari sumber dengan lebih banyak chapter
            k_ch = komiku_d.get('chapters') or []
            kiryuu_ch = kiryuu_d.get('chapters') or []
            if len(kiryuu_ch) > len(k_ch):
                komiku_d['chapters'] = kiryuu_ch
                komiku_d['total_chapters'] = len(kiryuu_ch)
            # Ambil rating dari sumber yang punya rating lebih tinggi
            k_rating = komiku_d.get('rating') or ''
            kiryuu_rating = kiryuu_d.get('rating') or ''
            if kiryuu_rating and not k_rating:
                komiku_d['rating'] = kiryuu_rating
            # Tambahkan info kiryuu jika komiku kosong
            for key in ('author', 'status', 'genre'):
                if not komiku_d.get(key) and kiryuu_d.get(key):
                    komiku_d[key] = kiryuu_d[key]
            # Tambahkan alt title kiryuu jika komiku kosong
            if not komiku_d.get('alt_title') and kiryuu_d.get('alt_title'):
                komiku_d['alt_title'] = kiryuu_d['alt_title']
            # Tambahkan similar dari kiryuu jika komiku kosong
            if not komiku_d.get('similar') and kiryuu_d.get('similar'):
                komiku_d['similar'] = kiryuu_d['similar']
        except Exception:
            pass
        return komiku_d

    data = cached(f"detail_{slug}", _detail, ttl=1800)
    _edge_cache(response, s_maxage=600, swr=1800)
    return data

@app.get("/api/chapter/{slug}/{chapter}", response_model=List[str])
def chapter(slug: str, chapter: str = Path(..., pattern=r'^\d+(-\d+)?$'), response: Response = None):
    key = f"chap_{slug}_{chapter}"
    hit = get_cache(key)
    if hit is not None:
        _edge_cache(response, s_maxage=900, swr=3600, browser=300)
        return hit
    # Coba komiku dulu, lalu fallback ke kiryuu
    try:
        images = api.chapter(slug, chapter)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 502
        if code == 404:
            images = []
        else:
            images = []
    except requests.RequestException:
        images = []
    if not images:
        try:
            images = kiryuu.chapter_images(slug, chapter)
        except Exception:
            images = []
    if not images:
        raise HTTPException(status_code=404, detail="chapter tidak ditemukan")
    set_cache(key, images)
    _edge_cache(response, s_maxage=900, swr=3600, browser=300)
    return images

# --- IMAGE PROXY (cover, optimized) ---
# Host gambar yang diizinkan diproxy. Tanpa allowlist, /api/img jadi
# open proxy / vektor SSRF (bisa dipakai menembak jaringan internal).
IMG_HOST_SUFFIXES = ('komiku.org', 'komiku.id', 'komiku.to', 'kiryuu.to', 'v7.kiryuu.to', 'yuucdn.com')

def _img_host_allowed(host):
    host = (host or '').lower().split(':')[0]
    return any(host == s or host.endswith('.' + s) for s in IMG_HOST_SUFFIXES)

# --- env config (lihat README: Image Proxy → Environment Variables) ---
IMAGE_CACHE_DIR = os.environ.get('IMAGE_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'zomic-imgcache'))
IMAGE_MAX_BYTES = int(os.environ.get('IMAGE_MAX_BYTES', '12582912'))          # 12 MB
IMAGE_MAX_PIXELS = int(os.environ.get('IMAGE_MAX_PIXELS', '25000000'))        # 25 MP
IMAGE_CACHE_TTL = int(os.environ.get('IMAGE_CACHE_TTL', '2592000'))            # 30 hari
IMAGE_SOURCE_CACHE_TTL = int(os.environ.get('IMAGE_SOURCE_CACHE_TTL', '604800'))  # 7 hari
IMAGE_CACHE_MAX_BYTES = int(os.environ.get('IMAGE_CACHE_MAX_BYTES', '268435456'))  # 256 MB

_IMG_LOCK = threading.Lock()
_AVIF_OK = None


def _avif_supported():
    global _AVIF_OK
    if _AVIF_OK is None:
        try:
            _AVIF_OK = bool(features.check('avif'))
        except Exception:
            _AVIF_OK = False
    return _AVIF_OK


# --- cache disk (ephemeral, aman dihapus) ---
def _img_cache_dir():
    try:
        os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
    except OSError:
        pass
    return IMAGE_CACHE_DIR


def _img_cache_path(key):
    return os.path.join(_img_cache_dir(), key)


def _img_cache_get(key, ttl):
    path = _img_cache_path(key)
    try:
        st = os.stat(path)
        if time.time() - st.st_mtime > ttl:
            return None
        with open(path, 'rb') as fh:
            return fh.read()
    except OSError:
        return None


def _img_cache_put(key, data):
    if not data:
        return
    path = _img_cache_path(key)
    tmp = f"{path}.tmp{os.getpid()}"
    try:
        with open(tmp, 'wb') as fh:
            fh.write(data)
        with _IMG_LOCK:
            os.replace(tmp, path)
            _img_evict()
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _img_evict():
    """Hapus cache tertua bila total melebihi batas aman."""
    try:
        entries = [os.path.join(IMAGE_CACHE_DIR, f) for f in os.listdir(IMAGE_CACHE_DIR)]
    except OSError:
        return
    stats, total = [], 0
    for p in entries:
        try:
            st = os.stat(p)
            total += st.st_size
            stats.append((st.st_mtime, p))
        except OSError:
            continue
    if total <= IMAGE_CACHE_MAX_BYTES:
        return
    for _, p in sorted(stats):
        if total <= IMAGE_CACHE_MAX_BYTES:
            break
        try:
            size = os.path.getsize(p)
            os.remove(p)
            total -= size
        except OSError:
            continue


# --- download terbatas ---
_IMG_SESSION = requests.Session()
_IMG_SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Linux; Android 13) Chrome/120.0 Mobile',
    'Referer': 'https://komiku.org/',
})

_MIME = {'PNG': 'image/png', 'GIF': 'image/gif', 'WEBP': 'image/webp', 'JPEG': 'image/jpeg', 'AVIF': 'image/avif'}


def _sniff_format(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'PNG'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'GIF'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'WEBP'
    return 'JPEG'


def _ctype_from_bytes(data):
    return _MIME.get(_sniff_format(data), 'image/jpeg')


def _img_fetch(url):
    """Download dengan limit ukuran + cache source. Return (bytes, content-type)."""
    src_key = hashlib.sha256(('src:' + url).encode('utf-8')).hexdigest()
    cached_src = _img_cache_get(src_key, IMAGE_SOURCE_CACHE_TTL)
    if cached_src is not None:
        return cached_src, _ctype_from_bytes(cached_src)
    # Set referer berdasarkan host sumber
    low = url.lower()
    if 'kiryuu.to' in low or 'yuucdn.com' in low:
        _IMG_SESSION.headers['Referer'] = 'https://v7.kiryuu.to/'
    else:
        _IMG_SESSION.headers['Referer'] = 'https://komiku.org/'
    try:
        req = retry_get(_IMG_SESSION, url, timeout=(5, 15), stream=True)
        if req.status_code != 200:
            req.close()
            raise HTTPException(status_code=502, detail="upstream unavailable")
        ctype = req.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if not ctype.startswith('image/'):
            req.close()
            raise HTTPException(status_code=502, detail="not an image")
        chunks, total = [], 0
        for chunk in req.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > IMAGE_MAX_BYTES:
                req.close()
                raise HTTPException(status_code=502, detail="image too large")
            chunks.append(chunk)
        req.close()
    except HTTPException:
        raise
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="upstream error")
    data = b''.join(chunks)
    _img_cache_put(src_key, data)
    return data, ctype


def _pick_format(fmt, accept):
    if fmt == 'webp':
        return 'WEBP'
    if fmt == 'avif':
        return 'AVIF' if _avif_supported() else 'WEBP'
    if fmt == 'auto':
        if 'image/avif' in accept and _avif_supported():
            return 'AVIF'
        if 'image/webp' in accept:
            return 'WEBP'
        return 'JPEG'
    return None  # original → ditentukan dari source


def _process_image(data, width, eff_fmt, quality):
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(status_code=502, detail="invalid image")
    w, h = img.size
    if w <= 0 or h <= 0 or w * h > IMAGE_MAX_PIXELS:
        raise HTTPException(status_code=502, detail="image too large")
    if width and width < w:
        nh = max(1, int(round(h * width / w)))
        img = img.resize((width, nh), Image.LANCZOS)
    if eff_fmt in ('JPEG', 'WEBP', 'AVIF'):
        img = img.convert('RGB')
    out = io.BytesIO()
    if eff_fmt == 'JPEG':
        img.save(out, 'JPEG', quality=quality, optimize=True)
    elif eff_fmt == 'WEBP':
        img.save(out, 'WEBP', quality=quality, method=4)
    elif eff_fmt == 'AVIF':
        img.save(out, 'AVIF', quality=quality)
    else:
        img.save(out, eff_fmt)
    return out.getvalue()


def _img_source_hit(url):
    key = hashlib.sha256(('src:' + url).encode('utf-8')).hexdigest()
    return _img_cache_get(key, IMAGE_SOURCE_CACHE_TTL) is not None


@app.get("/api/img")
def proxy_image(
    request: Request,
    url: str = Query(..., min_length=1),
    w: int = Query(None, ge=120, le=800),
    q: int = Query(78, ge=45, le=95),
    format: str = Query('original', pattern=r'^(auto|original|webp|avif)$'),
):
    """Proxy cover dengan opsi optimasi.

    Legacy: /api/img?url=ORIGINAL  → passthrough konservatif.
    Opt:    /api/img?url=ORIGINAL&w=400&format=auto&q=78
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise HTTPException(status_code=400, detail="invalid url")
    if not _img_host_allowed(parsed.hostname):
        raise HTTPException(status_code=403, detail="host tidak diizinkan")

    optimize = w is not None or format in ('auto', 'webp', 'avif')

    if not optimize:
        # Legacy / original: tetap proxy biasa, cache konservatif.
        hit = 'HIT' if _img_source_hit(url) else 'MISS'
        data, ctype = _img_fetch(url)
        return Response(content=data, media_type=ctype,
                        headers={"Cache-Control": "public, max-age=86400, s-maxage=86400",
                                 "CDN-Cache-Control": "public, s-maxage=86400",
                                 "X-Image-Cache": hit})

    accept = (request.headers.get('Accept') or '')
    eff = _pick_format(format, accept)
    if eff is None:
        eff = _sniff_format(_img_fetch(url)[0])  # format=original

    # format=auto memilih output dari header Accept → response bervariasi per
    # browser. Vary: Accept wajib agar CDN tidak melayani AVIF ke browser yang
    # hanya mendukung JPEG/WebP. Format eksplisit tidak perlu Vary.
    vary = {'Vary': 'Accept'} if format == 'auto' else {}

    key = hashlib.sha256(f"{url}|{w or 0}|{q}|{eff}".encode('utf-8')).hexdigest()
    hit = _img_cache_get(key, IMAGE_CACHE_TTL)
    if hit is not None:
        return Response(content=hit, media_type=_MIME[eff],
                        headers={"Cache-Control": f"public, max-age={IMAGE_CACHE_TTL}, immutable, s-maxage={IMAGE_CACHE_TTL}",
                                 "CDN-Cache-Control": f"public, s-maxage={IMAGE_CACHE_TTL}, immutable",
                                 "X-Image-Cache": "HIT", **vary})

    src, ctype = _img_fetch(url)
    try:
        out = _process_image(src, w, eff, q)
    except HTTPException:
        raise
    except Exception:
        # Fallback aman: kirim source asli bila processing gagal.
        return Response(content=src, media_type=ctype,
                        headers={"Cache-Control": "public, max-age=86400, s-maxage=86400",
                                 "CDN-Cache-Control": "public, s-maxage=86400",
                                 "X-Image-Cache": "MISS", **vary})
    _img_cache_put(key, out)
    return Response(content=out, media_type=_MIME[eff],
                    headers={"Cache-Control": f"public, max-age={IMAGE_CACHE_TTL}, immutable, s-maxage={IMAGE_CACHE_TTL}",
                             "CDN-Cache-Control": f"public, s-maxage={IMAGE_CACHE_TTL}, immutable",
                             "X-Image-Cache": "MISS", **vary})

# --- FRONTEND ---
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
INDEX_PATH = os.path.join(WEB_DIR, "index.html")


@app.get("/health")
def health(deep: int = Query(0, ge=0, le=1)):
    """Health check ringan untuk deployment: tanpa scraping upstream.

    Default hanya mengembalikan status aplikasi + versi. Diagnostic upstream
    (REST API + scraper katalog) tersedia via /health?deep=1 dan TIDAK boleh
    dipakai sebagai health check deployment karena bergantung pada upstream.
    """
    out = {"status": "ok", "version": app.version}
    if not deep:
        return out
    try:
        out["comics_found"] = len(api.latest(1))
    except Exception as e:
        out["status"] = "error"
        out["latest_error"] = str(e)
    try:
        out["catalog_total"] = web.catalog(1)["total"]
    except Exception as e:
        out["status"] = "degraded" if out["status"] == "ok" else "error"
        out["catalog_error"] = str(e)
    return out


@app.get("/", response_class=HTMLResponse)
def root():
    try:
        with open(INDEX_PATH, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())
    except OSError:
        raise HTTPException(status_code=500, detail="frontend tidak ditemukan: web/index.html")


# Font self-host frontend. Nama file divalidasi ketat (tanpa path traversal),
# dan di-cache immutable karena berisi hash versi dari subset Poppins.
FONT_RE = re.compile(r"poppins-(400|600|700|800)\.woff2$")


@app.get("/fonts/{name}")
def font_file(name: str, response: Response):
    if not FONT_RE.fullmatch(name):
        raise HTTPException(status_code=404)
    path = os.path.join(WEB_DIR, "fonts", name)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        raise HTTPException(status_code=404)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return Response(data, media_type="font/woff2")


# --- RUN ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
