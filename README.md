# Zomic — Web Komik (Manga Reader)

Web komik yang mengambil data dari **komiku.org**: katalog lengkap **7.615+ komik**,
pencarian global, filter genre/tipe/huruf, detail lengkap, dan reader dengan
gambar ter-proxy (lolos hotlink protection).

## Fitur

- Katalog lengkap semua komik (`/api/catalog`, 50/halaman → 153 halaman)
- Pencarian ke seluruh katalog (`/api/search`), bukan hanya komik terbaru
- 109 genre (`/api/genres` + `/api/genre/{slug}`)
- Populer per tipe, rekomendasi, dan komik berwarna
- Detail komik lengkap: sinopsis, status, author, rating, tanggal chapter, komik serupa
- Reader vertikal dengan navigasi prev/next chapter & shortcut keyboard (←/→/Esc)
- Favorit, riwayat baca, penanda chapter sudah dibaca (tersimpan di browser via localStorage)
- Filter tipe (manga/manhwa/manhua) & huruf awal A–Z
- Tema gelap/terang
- Proxy gambar ter-batas: hanya host `*.komiku.org` yang diizinkan (anti-SSRF)

## Struktur

```
app.py           Backend FastAPI (endpoint + serve frontend)
komiku_web.py    Scraper HTML komiku.org (katalog, search, genre)
web/index.html   Frontend SPA (hash router, tanpa build)
run.sh           Auto-setup venv + deps + verifikasi + jalankan
requirements.txt Dependensi Python
tests/           Unit test (unittest)
```

## Cara Jalankan

### Cara 1 — otomatis (disarankan)

```bash
bash run.sh
```

Script ini otomatis:
1. Membuat virtualenv `.venv` (fallback `--without-pip` + bootstrap `pip`)
2. Install `fastapi`, `uvicorn`, `requests`, `Pillow`
3. Cek syntax & koneksi ke komiku.org
4. Membebaskan port 8000 jika dipakai
5. Menjalankan server & verifikasi `/health`, frontend, dan semua endpoint utama

Server jalan di **http://localhost:8000**

> Jika `pip`/`venv` tidak ada di sistem (mis. WSL/Ubuntu tanpa `python3-venv`),
> install dulu dengan `sudo apt install python3-venv`.

### Cara 2 — manual

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt

python app.py                     # atau: uvicorn app:app --host 0.0.0.0 --port 8000
```

Buka **http://localhost:8000** (port diambil dari env `PORT`, fallback lokal 8000).

### Cara 3 — Docker

```bash
docker build -t zomic .
docker run --rm -p 8000:8000 -e PORT=8000 zomic
```

Dockerfile menjalankan web komik utama (`python app.py`), bukan backend scraper.
`app.py` membaca `PORT` dari environment (tidak hardcode untuk production).

## Akses dari Device Lain (satu WiFi)

Server sudah listen di `0.0.0.0`, jadi cukup akses dari device lain dengan IP
komputer di jaringan:

```
http://<IP-KOMPUTER>:8000
```

Cari IP komputer: `hostname -I` (Linux) atau `ipconfig` (Windows).

**Khusus WSL2** (ini lingkungan pengembangan bawaan proyek): WSL2 memakai NAT,
jadi IP `172.x.x.x` dari dalam WSL tidak bisa diakses device lain. Perlu
port-forward di Windows (jalankan di **PowerShell Administrator** sekali saja):

```powershell
# Ganti 172.x.x.x dengan IP WSL saat ini (cek: hostname -I)
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=172.x.x.x
netsh advfirewall firewall add rule name=Zomic8000 dir=in action=allow protocol=TCP localport=8000
```

Lalu akses dari HP/PC lain via IP Wi-Fi Windows (cek: `ipconfig` → "Wi-Fi" →
IPv4), mis. `http://192.168.165.103:8000`.

> IP WSL berubah tiap restart WSL — ulangi perintah portproxy jika WSL/laptop
> di-restart (`netsh interface portproxy set v4tov4 ... connectaddress=<IP baru>`).

## Endpoint API

| Endpoint | Keterangan |
| --- | --- |
| `/api/latest` | Komik terbaru (20 item) |
| `/api/catalog?page=&type=&letter=` | Katalog lengkap (manga/manhwa/manhua, A–Z) |
| `/api/search?q=&page=` | Pencarian seluruh katalog |
| `/api/genres` | Daftar 109 genre |
| `/api/genre/{slug}?page=` | Komik per genre |
| `/api/popular` | Populer per tipe |
| `/api/recommended` | Rekomendasi (40 item) |
| `/api/colored` | Komik berwarna |
| `/api/detail/{slug}` | Detail komik + chapter |
| `/api/chapter/{slug}/{chapter}` | Daftar URL gambar (array) |
| `/api/img?url=` | Proxy gambar legacy (allowlist `*.komiku.org` / `*.komiku.id`) |
| `/api/img?url=&w=&format=&q=` | Proxy cover ter-optimasi (resize + AVIF/WebP/JPEG + cache) |
| `/health` | Status server + katalog |

## Image Proxy

### Legacy (`/api/img?url=ORIGINAL`)

Passthrough konservatif — dipakai untuk **halaman reader** agar kualitas gambar
komik tidak turun. Cache `public, max-age=86400`.

### Optimized (`/api/img?url=ORIGINAL&w=400&format=auto&q=78`)

Dipakai untuk **cover** (card 240/400px, detail 800px):

- `w`: integer 120–800 (tidak pernah upscale).
- `q`: integer 45–95.
- `format`: `auto` (AVIF → WebP → JPEG sesuai `Accept`), `original`, `webp`, `avif`.
- Hanya host `*.komiku.org` dan `*.komiku.id` (tolak localhost/private IP/SSRF).
- Batas download 12 MB dan batas dimensi 25 MP (anti decompression bomb).
- Cache disk `SHA-256` (url + w + format + q), atomic write, evict tertua saat
  melebihi batas, header `Cache-Control: public, max-age=2592000, immutable`.
- Header diagnostik `X-Image-Cache: HIT/MISS`.

### Environment Variables

| Variable | Default | Fungsi |
| --- | --- | --- |
| `PORT` | `8000` | Port listen (dipakai production, mis. Render) |
| `IMAGE_CACHE_DIR` | `/tmp/zomic-image-cache` | Direktori cache gambar |
| `IMAGE_MAX_BYTES` | `12582912` | Batas ukuran download (12 MB) |
| `IMAGE_MAX_PIXELS` | `25000000` | Batas dimensi/decompression bomb (25 MP) |
| `IMAGE_CACHE_TTL` | `2592000` | TTL variant cache (30 hari) |
| `IMAGE_SOURCE_CACHE_TTL` | `86400` | TTL cache source asli (1 hari) |
| `IMAGE_CACHE_MAX_BYTES` | `268435456` | Batas total cache disk (256 MB) |

Cache pada Render Free bersifat **ephemeral** (filesystem tidak persisten):
service akan tidur setelah idle dan cache hilang saat restart — itu normal.

## Menjalankan Tes

```bash
.venv/bin/python -m unittest discover -s tests -q
```

## Deploy ke Render (Web Service Free)

Deploy sebagai **Web Service** (bukan Static Site) dengan native Python runtime:

```text
Build Command:  pip install -r requirements.txt
Start Command:  python app.py
Health Check:   /health
Region:         singapore
Plan:           free
```

- `render.yaml` di repo sudah berisi konfigurasi tersebut beserta environment
  variables image cache. Render otomatis menyuntikkan `PORT` — jangan hardcode
  port 8000 untuk production; `app.py` membaca `PORT`.
- Import repository ke Render → *New + → Blueprint* memakai `render.yaml`.
- Catatan Render Free: service tidur setelah ~15 menit idle dan akan "cold start"
  saat ada request berikutnya. Filesystem cache (`/tmp`) tidak persisten.
- Reader image tidak dioptimalkan (legacy `/api/img?url=`) supaya halaman komik
  tetap resolusi tinggi; hanya cover yang di-resize/compress.

## Keterbatasan (upstream komiku.org)

- REST API pihak ketiga (`api-komiku.vercel.app`) mengabaikan parameter `page`
  di `/terbaru` dan `/search`-nya rusak (HTTP 500) — karena itu katalog & search
  diambil langsung via scraping HTML `komiku.org`.
- `komiku.org` membatasi 10 hasil per halaman untuk search & genre sesuai
  template situsnya; `has_next` pada keduanya adalah perkiraan.
- Search hanya cocok dengan judul (bukan sinopsis).

## Keamanan

- `/api/img` hanya memproxy host yang berakhiran `komiku.org` atau `komiku.id`
  (subdomain sesuai, suffix exact match → host seperti `komiku.org.evil.com` ditolak).
  URL ke IP internal (`169.254.*`, `localhost`, alamat LAN) tidak lolos allowlist →
  mencegah SSRF. Scheme selain `http/https` ditolak.
- Download dibatasi (12 MB) dan dimensi dibatasi (25 MP) untuk mencegah
  decompression bomb; parameter `w`/`q`/`format` divalidasi dengan batas aman.
- Semua output teks dari upstream di-escape di frontend (anti-XSS).