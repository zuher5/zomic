# AGENTS.md

Panduan singkat untuk agent coding yang bekerja di repo ini.

## Stack

- **Backend**: FastAPI (`app.py`) — satu file utama.
- **Frontend**: SPA tanpa build (`web/index.html`).
- **Scrapers/native clients**: `komiku_web.py`, `kiryuu_web.py`, `voratoon_web.py`.
- **Deploy**:
  - **Production persisten**: FastAPI Cloud (`pyproject.toml`, `.fastapicloudignore`).
  - **Cadangan/pause**: Vercel (`vercel.json`, `api/index.py`) — project di dashboard saat ini **di-pause**; jangan buru-buru debug kegagalan Vercel.
- **Runtime local**: `bash run.sh` atau `WORKERS=1 python3 -u app.py`.

## Aturan wajib

1. **Tidak menambah dependency berat** (BeautifulSoup, Node sidecar, framework frontend build).
2. **Mock semua HTTP call di test** (`unittest.TestCase`). Test harus jalan tanpa jaringan: `python3 -m unittest discover tests`.
3. **Anti-SSRF ketat** pada image proxy: host harus lolos `_img_host_allowed()` di `app.py`.
4. **Env config terbatas**: `WORKERS`, `PORT`, `IMAGE_CACHE_TTL`, `IMG_HOST_SUFFIXES_EXTRA`.
5. **Vercel di-pause**: kegagalan `vercel[bot]`/`Deployment was blocked` adalah normal; prioritas diagnosa ke FastAPI Cloud.
6. **Kompatibilitas Termux/Android**: default `WORKERS=1`, hindari dependency yang butuh kompelasi native.
7. **Jangan commit secret/token** atau file log/`.venv/`/cache.

## Struktur file penting

```text
app.py              FastAPI app + endpoint + image proxy
komiku_web.py       Scraper komiku.org
kiryuu_web.py       Scraper kiryuu.to
voratoon_web.py     Native client v5.voratoon.com
web/index.html      SPA reader/catalog
api/index.py        Vercel serverless entrypoint (cadangan)
run.sh              Setup + verify + run local
tests/              Unittest mocked HTTP
```

## Verifikasi sebelum push

```bash
python3 -m unittest discover tests
python3 -m py_compile app.py komiku_web.py kiryuu_web.py voratoon_web.py
bash run.sh          # optional, menjalankan smoke test live
```
