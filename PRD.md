# PRD.md

## 1. Overview

**Zomic** adalah web reader komik/manga/manhwa/manhua yang mengagregasi katalog dari `komiku.org`, `kiryuu.to`, dan `v5.voratoon.com`. Backend memakai **FastAPI**; frontend adalah **SPA tanpa build** yang dilayani dari `web/index.html`.

## 2. Goals

- Katalog lengkap semua komik dari sumber upstream.
- Search global, detail komik, genre, populer, rekomendasi.
- Reader vertikal dengan navigasi prev/next, progress scroll, history, favorit.
- Proxy gambar aman (`/api/img`) dengan allowlist host.
- Bisa dijalankan di Termux/Android dengan resource terbatas.

## 3. Non-Goals

- Hosting gambar komik sendiri.
- Sistem login/akun server-side.
- Build frontend (React/Vue/Next/Vite) di pipeline build.
- Node.js sidecar runtime.

## 4. Architecture

- **FastAPI** (`app.py`): endpoint API, cache in-memory, rate limiting, security headers, image proxy, SPA fallback.
- **Scrapers/Clients**:
  - `komiku_web.py`: HTML scraping katalog & search.
  - `kiryuu_web.py`: HTML scraping katalog/chapter.
  - `voratoon_web.py`: native client v5.voratoon.com.
- **Frontend**: `web/index.html` — hash router, localStorage untuk favorit/history/progress.
- **Deploy**:
  - **FastAPI Cloud**: production server persisten.
  - **Vercel**: cadangan, project di-pause di dashboard sampai admin mengaktifkan kembali.

## 5. User Flows

1. Buka home → lihat latest/popular/recommended → pilih komik.
2. Detail → baca sinopsis, genre, daftar chapter.
3. Reader → scroll gambar, auto next chapter via prev/next, shortcut keyboard.
4. Catalog/Search → filter tipe/genre/huruf → buka detail.
5. Koleksi → lihat favorit & history (localStorage).

## 6. Key Requirements

### Functional

- `/api/latest`, `/api/catalog`, `/api/search`, `/api/popular`, `/api/recommended`, `/api/detail/{slug}`, `/api/chapter/{slug}/{ch}`.
- `/api/img?url=` memproxy gambar hanya dari host allowlist.
- Reader halaman chapter memuat daftar gambar dari API.

### Non-Functional

- `WORKERS=1` default untuk Termux.
- `cached()` dengan stale cache saat upstream gagal.
- Test harus mock semua HTTP; tidak boleh memanggil network luar.
- Vercel paused: status Vercel failure/blocked tidak dianggap bug kode.

## 7. Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` | Port server local. |
| `WORKERS` | `1` (cloud via `fastapi run`) | Jumlah worker uvicorn. |
| `IMAGE_CACHE_TTL` | 30 hari | Masa simpan cache gambar. |
| `IMG_HOST_SUFFIXES_EXTRA` | kosong | Host CDN tambahan untuk image proxy. |

## 8. Deployment Notes

- Push ke `main` akan memicu FastAPI Cloud deploy sukses.
- Push ke `main` akan memicu Vercel `Deployment was blocked` — **normal** karena project di-pause.
- Untuk mengaktifkan Vercel kembali: dashboard Vercel → project `zomic` → Unpause → push ulang.

## 9. Constraints & Risks

- Upstream bisa berubah struktur HTML/JSON; scraper perlu maintenance.
- Rate limit/anti-bot (mis. DDoS-Guard) dapat membuat scraper lambat; fallback stale cache.
- Disk cache pada FastAPI Cloud bersifat ephemeral.
