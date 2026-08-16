# Prompt OpenCode — Verifikasi Kondisional dan Deployment Zomic

## Instruksi Eksekusi Paling Penting

Proyek ZIP Zomic sudah diimport ke direktori kerja OpenCode. Jangan mengasumsikan proyek masih dalam kondisi awal dan jangan mengulang semua perubahan secara membabi buta.

Sebelum mengubah file, audit kondisi aktual repository yang sedang dibuka. Buat matriks verifikasi internal untuk setiap requirement dengan status berikut:

- `PASS / SKIP`: implementasi sudah benar, test atau inspeksi membuktikannya, dan tidak perlu diedit.
- `FAIL / FIX`: implementasi belum ada, salah, rusak, tidak aman, atau test gagal; perbaiki hanya bagian tersebut.
- `UNKNOWN / VERIFY`: belum cukup bukti; lakukan pemeriksaan atau test tambahan sebelum memutuskan.

Jika statusnya `PASS / SKIP`, jangan mengubah file terkait, jangan memformat ulang kode yang tidak relevan, jangan mengganti implementasi yang sudah bekerja, dan jangan menambahkan dependency duplikat. Jika statusnya `FAIL / FIX`, lakukan perubahan paling kecil yang menyelesaikan masalah, lalu jalankan test yang relevan. Jika perubahan ternyata sudah ada di proyek hasil import, cukup verifikasi dan lanjutkan.

Jangan mengganti seluruh file dengan versi baru hanya karena sebagian kecil perlu diperbaiki. Jangan menghapus cache, konfigurasi, test, atau fitur lama yang sudah benar. Jangan berhenti setelah audit; lanjutkan memperbaiki semua status `FAIL / FIX`, menjalankan validasi, dan melaporkan bagian yang di-skip.

Di laporan akhir wajib tuliskan matriks ringkas:

```text
REQUIREMENT | STATUS PASS/SKIP atau FAIL/FIX | BUKTI VERIFIKASI | FILE YANG DIUBAH
```

Setelah aturan eksekusi di atas dipatuhi, lanjutkan dengan instruksi berikut.

## Checkpoint Input Pengguna Saat Deploy

Jika proses deployment memerlukan input pribadi atau tindakan manual pengguna, berhenti sementara dan minta input tersebut. Jangan menebak, jangan memakai email dummy, jangan membuat akun baru tanpa persetujuan, dan jangan melanjutkan ke langkah berikutnya sebelum pengguna menjawab.

Kondisi yang wajib memicu checkpoint antara lain:

- Render atau layanan hosting meminta email.
- Proses meminta login, username, password, API key, access token, SSH key, atau verifikasi dua faktor.
- Proses meminta konfirmasi akun, verifikasi email, persetujuan deployment, atau pemilihan repository privat.
- Proses meminta informasi pembayaran, kartu, atau billing.
- Browser menampilkan CAPTCHA, device verification, atau halaman yang membutuhkan tindakan manual.

Gunakan format permintaan berikut:

```text
INPUT_REQUIRED
Field: email / login / verification / credential
Reason: jelaskan langkah deployment yang sedang menunggu input
Action: kirim input yang aman atau selesaikan langkah tersebut secara manual, lalu beri tahu saya untuk melanjutkan
```

Untuk email, pengguna boleh memberikan alamat email melalui percakapan. Untuk password, API key, token, kode 2FA, dan informasi kartu, jangan menulis, mencetak ulang, atau menyimpan nilainya ke repository, log, prompt, atau file konfigurasi. Minta pengguna memasukkannya langsung pada halaman atau terminal miliknya jika memungkinkan. Setelah pengguna memberikan input yang diperlukan atau mengonfirmasi bahwa langkah manual sudah selesai, lanjutkan dari checkpoint terakhir tanpa mengulang perubahan yang sudah berstatus `PASS / SKIP`.

Anda adalah senior full-stack engineer yang bertugas memperbaiki dan menyiapkan aplikasi Zomic untuk deployment. Kerjakan langsung pada repository yang sedang aktif. Jangan hanya memberikan saran atau diff; lakukan perubahan pada file, jalankan validasi, perbaiki error yang ditemukan, dan buat laporan akhir.

## Tujuan Utama

Siapkan aplikasi Zomic agar:

1. Berjalan stabil sebagai aplikasi FastAPI utama.
2. Tidak lagi menjalankan backend alternatif yang salah saat deployment.
3. Tidak menampilkan upstream error untuk gangguan upstream yang bersifat sementara.
4. Memiliki image proxy cover yang ringan, tajam, aman, dan menggunakan cache.
5. Memiliki grid Genre tanpa baris atau kolom kosong yang berbeda warna.
6. Menggunakan lazy loading untuk cover di bawah viewport.
7. Mempertahankan resolusi tinggi untuk halaman reader komik.
8. Memiliki konfigurasi deployment yang siap dipakai sebagai Render Web Service gratis.
9. Mempertahankan seluruh fungsi yang sudah ada dan tidak melakukan redesign UI.

## Aturan Kerja

Bekerjalah secara bertahap. Sebelum mengubah kode, audit struktur repository, entrypoint, backend, frontend, requirements, Dockerfile, konfigurasi deployment, test, dan log error. Jangan berasumsi bahwa file berada di root; cari file sebenarnya terlebih dahulu.

Jangan menghapus fungsi lama kecuali terbukti salah. Jangan mengubah kontrak endpoint API yang sudah dipakai frontend. Jangan mengubah visual identity, warna utama, tipografi, atau arsitektur frontend tanpa alasan teknis yang jelas.

Jika ada file ZIP, ekstrak ke workspace kerja dan pastikan repository root tidak memiliki folder bersarang yang menyebabkan `app.py`, `requirements.txt`, atau `web/` tidak terdeteksi saat deploy.

Jika ada perubahan yang tidak dapat dilakukan karena credential atau akses layanan eksternal tidak tersedia, tetap siapkan seluruh file konfigurasi dan berikan instruksi manual yang tersisa. Jangan mengarang bahwa deployment sudah berhasil jika belum benar-benar diverifikasi.

## Fase 1 — Audit dan Diagnosis

Lakukan audit berikut:

- Temukan entrypoint FastAPI utama dan pastikan objek ASGI bernama `app` tersedia.
- Temukan semua endpoint `/api/*`, `/health`, `/api/img`, dan penggunaan `/api/img` pada frontend.
- Temukan backend alternatif atau service lama yang mungkin tidak menyediakan endpoint Zomic seperti `/api/latest`, `/api/catalog`, `/api/genres`, `/api/popular`, dan `/api/recommended`.
- Periksa `Dockerfile`, `run.sh`, `README.md`, `requirements.txt`, dan seluruh konfigurasi deployment.
- Cari semua penggunaan `<img>`, `srcset`, `loading`, dan pembentukan URL cover.
- Audit keamanan image proxy: allowlist host, scheme, SSRF, private IP, ukuran download, dimensi gambar, decompression bomb, dan format yang tidak didukung.
- Jalankan test yang sudah tersedia sebelum mengubah kode jika memungkinkan.
- Cari error `502`, `upstream error`, `Bad Gateway`, timeout, dan `No open ports detected` pada log atau test.

Buat catatan diagnosis internal sebelum implementasi, tetapi jangan berhenti hanya pada diagnosis.

## Fase 2 — Perbaiki Upstream Error dan Runtime

Pastikan aplikasi web utama dijalankan oleh `app.py`, bukan `backend.api:app` jika backend tersebut tidak memiliki endpoint frontend Zomic.

Pastikan server bind ke:

```text
0.0.0.0:$PORT
```

Jika `app.py` memiliki fallback port lokal, gunakan `PORT` dari environment variable dengan fallback lokal hanya untuk development.

Untuk request ke upstream `komiku.org` dan REST API pihak ketiga:

- Tambahkan retry terbatas hanya untuk request GET.
- Gunakan exponential backoff ringan.
- Retry status `429`, `500`, `502`, `503`, dan `504` serta error koneksi/read timeout.
- Jangan membuat retry tak terbatas.
- Pertahankan mapping error HTTP yang jelas jika seluruh retry gagal.
- Pastikan response error tidak membocorkan path internal atau detail sensitif.
- Jangan mengubah response sukses endpoint yang sudah digunakan frontend.

Jika ada filter katalog yang kadang gagal karena upstream, sediakan fallback yang aman atau error yang jelas tanpa merusak hasil normal. Semua fallback harus diuji.

## Fase 3 — Optimasi Image Proxy Cover

Pertahankan kompatibilitas endpoint lama:

```text
/api/img?url=ORIGINAL_URL
```

Tambahkan dukungan opsional:

```text
/api/img?url=ORIGINAL_URL&w=400&format=auto&q=78
```

Parameter harus divalidasi dengan batas aman:

- `w`: integer antara 120 dan 800.
- `q`: integer antara 45 dan 95.
- `format`: `auto`, `original`, `webp`, atau `avif`.
- Jangan menerima URL selain `http` atau `https`.
- Hanya izinkan host resmi yang sudah digunakan Zomic seperti `*.komiku.org` dan `*.komiku.id`.
- Tolak localhost, loopback, private IP, metadata IP, host palsu, dan scheme lain.
- Batasi ukuran download asli, misalnya maksimum 12 MB.
- Batasi dimensi/decompression bomb, misalnya maksimum sekitar 25 megapixel.
- Gunakan timeout koneksi dan timeout read.

Gunakan Pillow atau image library yang sesuai. Tambahkan dependency produksi secara eksplisit pada `requirements.txt`.

Strategi output:

- Cover kecil/mobile: 240px.
- Cover card: 400px.
- Detail/ukuran besar: 800px.
- Jangan upscale gambar yang lebih kecil dari ukuran permintaan.
- Pertahankan aspect ratio.
- Jangan crop cover manga.
- Pilih AVIF jika tersedia dan diterima browser.
- Gunakan WebP sebagai fallback.
- Gunakan JPEG/PNG/original jika encoding gagal atau hasil optimized tidak aman.
- Jangan mengubah endpoint gambar halaman reader menjadi thumbnail.

Cache:

- Buat cache key deterministik dari URL asli, width, format, dan quality menggunakan SHA-256.
- Jangan menggunakan raw URL sebagai nama file.
- Gunakan atomic write agar file cache tidak korup.
- Gunakan cache source dan cache variant jika sesuai.
- Hapus cache tertua apabila melewati batas ukuran yang aman.
- Cache file boleh bersifat ephemeral pada Render Free; jangan menganggap filesystem lokal sebagai storage permanen.
- Gunakan header browser/CDN yang sesuai untuk variant URL yang stabil, misalnya `public, max-age=2592000, immutable`.
- Untuk legacy/original response, gunakan cache policy yang lebih konservatif.
- Tambahkan header diagnostik ringan seperti `X-Image-Cache: HIT/MISS` hanya jika tidak membocorkan informasi sensitif.
- Jika processing gagal, tetap kembalikan source image yang valid jika memungkinkan.

## Fase 4 — Frontend Image Delivery dan Lazy Loading

Jangan redesign UI. Ubah hanya image delivery.

Untuk cover card:

- Gunakan `loading="lazy"`.
- Gunakan `decoding="async"`.
- Gunakan `srcset` dengan variant sekitar 240w, 400w, dan 800w.
- Gunakan `sizes` yang mengikuti layout aktual.
- Jangan memakai `fetchpriority="high"` untuk semua gambar.
- Jangan eagerly load semua cover di halaman Home.
- Cover yang memang terlihat pada halaman detail boleh menggunakan `loading="eager"`.
- Dua halaman pertama reader boleh eager; halaman berikutnya tetap lazy.
- Pastikan tidak ada horizontal overflow.
- Pastikan URL reader tetap menggunakan endpoint legacy tanpa `w` agar kualitas halaman komik tidak turun.

Pastikan HTML hasil rendering tidak menghasilkan atribut kosong atau URL rusak.

## Fase 5 — Perbaiki Grid Genre dan Populer

Pada grid Genre:

- Hapus `background: var(--line)` dari parent grid jika itu mengisi sel kosong pada baris terakhir dengan warna berbeda.
- Gunakan `background: transparent` pada parent grid.
- Gunakan `gap` yang konsisten.
- Semua item Genre harus memiliki warna background yang sama.
- Gunakan padding yang konsisten pada semua breakpoint.
- Jangan membuat sel placeholder kosong hanya untuk memenuhi grid.
- Pastikan baris terakhir yang jumlah itemnya tidak penuh tidak menampilkan blok warna kosong.

Pada bagian Populer:

- Tampilkan maksimal 4 baris per panel, bukan 8.
- Pertahankan tab populer dan fungsi navigasinya.
- Pastikan menu/navigasi Genre tetap tersedia pada desktop dan mobile.

## Fase 6 — Render Web Service Configuration

Siapkan deployment sebagai **Render Web Service**, bukan Static Site.

Gunakan native Python runtime jika tidak ada kebutuhan OS khusus:

```text
Build Command: pip install -r requirements.txt
Start Command: python app.py
Health Check Path: /health
Region: singapore
Plan: free
```

Pastikan service membaca `PORT` dari environment Render. Jangan hardcode port 8000 untuk production.

Buat atau perbarui `render.yaml` jika schema Render terbaru mendukung konfigurasi berikut. Verifikasi format schema yang dipakai sebelum menyimpan:

```yaml
services:
  - type: web
    name: zomic
    runtime: python
    plan: free
    region: singapore
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
    healthCheckPath: /health
    envVars:
      - key: IMAGE_CACHE_DIR
        value: /tmp/zomic-image-cache
      - key: IMAGE_MAX_BYTES
        value: "12582912"
      - key: IMAGE_MAX_PIXELS
        value: "25000000"
      - key: IMAGE_CACHE_TTL
        value: "2592000"
      - key: IMAGE_SOURCE_CACHE_TTL
        value: "86400"
      - key: IMAGE_CACHE_MAX_BYTES
        value: "268435456"
```

Jika menggunakan Dockerfile, pastikan command tidak hardcode port 8000. Gunakan salah satu pola yang membaca environment `PORT`, atau gunakan:

```dockerfile
CMD ["python", "app.py"]
```

Pastikan Dockerfile menjalankan `app:app`, bukan backend alternatif yang tidak memiliki endpoint frontend Zomic.

Jangan menambahkan secret ke Git. Jika ada token atau credential, masukkan hanya melalui Render Environment Variables.

## Fase 7 — Testing dan Validasi

Jalankan seluruh validasi yang tersedia:

```bash
python3 -m py_compile app.py komiku_web.py
python3 -m unittest discover -s tests -q
```

Jika frontend memiliki inline JavaScript, ekstrak dan validasi syntax dengan Node.js tanpa mengeksekusi request eksternal.

Jalankan smoke test server lokal menggunakan port sementara:

```bash
PORT=18080 python3 app.py
```

Uji endpoint berikut:

```text
/
/health
/api/latest
/api/catalog?page=1
/api/catalog?page=1&type=manga
/api/catalog?page=1&type=manhwa
/api/catalog?page=1&type=manhua
/api/search?q=naruto
/api/genres
/api/genre/action?page=1
/api/popular
/api/recommended
/api/colored
```

Uji security image proxy:

- URL valid dari allowlist harus diterima.
- `file:///etc/passwd` harus ditolak.
- `http://localhost:8000/health` harus ditolak.
- `http://127.0.0.1/...` harus ditolak.
- `http://169.254.169.254/...` harus ditolak.
- Host mirip seperti `komiku.org.evil.com` harus ditolak.

Uji image optimization dengan satu cover representative:

1. Request legacy tanpa `w`.
2. Request `w=400&format=auto&q=78` dengan `Accept: image/avif,image/webp,image/*`.
3. Request kedua dengan URL variant yang sama.
4. Pastikan request kedua menunjukkan cache hit.
5. Catat content type dan ukuran file.
6. Bandingkan ukuran original dengan optimized.
7. Pastikan optimized image masih dapat dibuka dan tidak crop.

Uji frontend:

- Home tampil.
- Genre tampil tanpa blok warna kosong pada baris terakhir.
- Cover card memiliki `loading="lazy"` dan `decoding="async"`.
- Detail tampil.
- Reader tetap memakai gambar resolusi asli.
- Tidak ada horizontal overflow.
- Tidak ada JavaScript syntax error.

Jika Docker tersedia, jalankan:

```bash
docker build -t zomic-test .
```

Jangan menganggap deployment Render berhasil sebelum ada bukti dari log atau endpoint publik. Jika credential Render CLI tidak tersedia, siapkan file dan instruksi, lalu laporkan bahwa login/deploy manual masih diperlukan.

## Fase 8 — Kualitas Kode dan Dokumentasi

Perbarui README agar menjelaskan:

- Cara menjalankan lokal.
- Endpoint image proxy legacy dan optimized.
- Environment variables image cache.
- Cara deploy Render Web Service.
- Port harus berasal dari `PORT`.
- Free Render sleep setelah idle dan filesystem cache tidak persisten.
- Reader image tidak dioptimalkan seperti cover.

Tambahkan atau perbarui test untuk:

- validasi parameter image proxy,
- allowlist/SSRF,
- resizing dan format output,
- fallback saat encoding gagal,
- cache hit/miss,
- endpoint `/health`,
- grid Genre dan lazy loading jika frontend test tersedia.

## Definition of Done

Pekerjaan dianggap selesai hanya jika semua kondisi berikut terpenuhi:

- Aplikasi utama berjalan dari entrypoint yang benar.
- `PORT` dan `0.0.0.0` digunakan.
- Endpoint utama tidak menggunakan backend yang salah.
- Upstream retry terbatas berfungsi.
- Unit test lulus.
- Syntax Python dan JavaScript lulus.
- Image proxy legacy tetap kompatibel.
- Cover menggunakan ukuran 240/400/800 sesuai kebutuhan.
- WebP/AVIF dipakai jika tersedia.
- Cache image menggunakan key hash dan header yang benar.
- Fallback image tetap bekerja.
- Reader page tidak terdegradasi.
- Genre tidak menampilkan sel kosong berbeda warna.
- Cover di bawah viewport lazy-loaded.
- Render Web Service configuration siap digunakan.
- Tidak ada secret yang ditulis ke repository.
- Laporan akhir mencantumkan file yang diubah, test yang dijalankan, hasil smoke test, dan langkah manual yang masih membutuhkan login pengguna.

Pada laporan akhir, gunakan format:

```text
STATUS: PASS atau BLOCKED
CHANGED: daftar file yang diubah
TESTS: daftar test dan hasilnya
IMAGE BENCHMARK: ukuran sebelum/sesudah dan cache hit/miss
DEPLOY: status konfigurasi Render dan apakah deploy publik berhasil
NEXT: langkah manual yang masih diperlukan
```
