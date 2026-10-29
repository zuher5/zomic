# Rancangan: Recommended For You v2

Status: **rancangan, belum diimplementasi**. Dibuat dari audit kode dan probe
live pada `api-komiku.vercel.app` serta endpoint terkait.

## 1. Masalah (diverifikasi)

- `/api/recommended` hanya mengambil 10 item teratas per sumber
  (`REC_POOL_PER_SOURCE`), lalu merotasi **urutannya** tiap 15 menit.
- Sumber rekomendasinya statis:
  - Komiku: `api-komiku.vercel.app/rekomendasi` — 3 panggilan berturut-turut
    menghasilkan daftar yang sama (Ao Ashi, Black Clover, Overgeared New, ...).
  - Kiryuu: `home(1)` 10 teratas (urutan halaman depan).
  - Voratoon: `popular()` / `latest(1)`.
  - Shinigami: `popular()` / `latest(1)`.
- Akibatnya set item yang muncul praktis tidak berubah; rotasi hanya mengocok
  posisi dari kumpulan yang sama.

## 2. Sumber REST yang tersedia (probe live)

| Endpoint | Status | Isi | Dipakai untuk |
|---|---|---|---|
| `/rekomendasi` | 200 | 10 item, statis | pool dasar (sudah ada) |
| `/terbaru` | 200 | 40 item update, ada `type`, `genre`, `mangaSlug` | pool "segar" (baru) |
| `/detail-komik/:slug` | 200 | `genres`, `similarKomik` (18 item + genre) | graf kemiripan (baru) |
| `/komik-populer` | 200 | kosong saat probe | tidak andal, skip |
| `/berwarna`, `/pustaka` | 200 | kosong saat probe | skip |
| `/trending`, `/genre-detail/:slug`, `/populer` | 404 | — | jangan dipakai |
| `/search?q=` | 500 (`Invalid URL`) | — | jangan dipakai |

Catatan: daftar endpoint di root (`/`) tidak sepenuhnya akurat; sebagian
menjawab 404. Setiap endpoint harus diuji sebelum dipakai.

## 3. Pendekatan

Ada tiga lapis, dari yang paling murah:

**A. Rotasi pool luas (sumber, bukan urutan).**
Ambil kandidat lebih banyak per sumber (mis. `/terbaru` 40 item, Kiryuu
`catalog` halaman acak 1–N, Voratoon `latest` halaman acak), lalu pilih
subset deterministik per window. Tujuan: set item yang muncul berubah.

**B. Rekomendasi berbasis kemiripan (content-based).**
Untuk satu "seed" komik (mis. item yang baru dibuka/difavoritkan user, atau
item acak dari pool `/terbaru`), ambil `detail-komik` → `similarKomik`.
Hasilnya kandidat yang relevan secara genre. Ini memberi variasi yang
bermakna, bukan acak murni.

**C. Diversifikasi genre.**
Saat menyusun rail, batasi jumlah item per genre utama (mis. maks 6 dari
satu genre) agar tidak didominasi satu genre.

Rekomendasi akhir = campuran: sebagian dari pool luas (A), sebagian dari
kemiripan seed (B), disaring oleh C, dedup per slug dan judul ternormalisasi
(sudah ada di `_rotate_recommended`).

## 4. Perubahan yang diusulkan

1. **Pool baru** `recommended_pool_wide` (TTL 6 jam): gabungkan
   `/rekomendasi` + `/terbaru` (40) + Kiryuu/Voratoon latest. Dedup.
2. **Seed per window**: pilih seed dari pool dengan `step` deterministik
   (`hash(slug) ^ step`), ambil `detail-komik` (cache 6 jam per slug), ambil
   `similarKomik` sebagai kandidat.
3. **Budget upstream**: tiap refresh hanya memanggil `detail-komik` untuk
   **N seed** (mis. 3). Batasi agar tidak membanjiri upstream dan tetap
   sesuai rate limit.
4. **Komposisi**: 12 item dari pool luas + 8 dari kemiripan, disaring
   diversifikasi genre (maks 6 per genre utama).
5. **Degradasi**: bila `api-komiku` gagal, pakai pool sumber lain saja
   (perilaku sekarang). Tidak ada hasil kosong yang menggantikan rail.
6. **Mode `/api/recommended?seed=<slug>`** (opsional, fase 2): rekomendasi
   langsung dari satu komik, untuk "Mirip dengan ini" di halaman detail.

## 5. Yang tidak dilakukan

- Tidak menambah dependency baru; cukup `requests` yang sudah ada.
- Tidak menyimpan data user di server (tetap stateless; seed dipilih
  deterministik, bukan dari riwayat user).
- Tidak mengandalkan `/search`, `/trending`, `/genre-detail`, `/populer`
  karena terbukti gagal.

## 6. Pengujian

- Tes mock semua HTTP (`unittest`): komposisi, diversifikasi genre, dedup,
  rotasi antar-window menghasilkan set berbeda, degradasi saat sumber gagal.
- Uji live manual: bandingkan daftar antar window 15 menit; target set item
  berubah minimal 50% antar window.

## 7. Risiko & pertanyaan terbuka

- `api-komiku.vercel.app` pihak ketiga; endpoint bisa hilang sewaktu-waktu.
  Perlu fallback yang sudah ada.
- Bila `similarKomik` berisi entri "[testing ...]" (terlihat di probe), perlu
  filter judul berawalan `[testing`.
- **Pertanyaan untuk Anda**: sumber REST lain apa yang Anda maksud? Jika ada
  endpoint lain (URL + contoh respons), saya masukkan ke probe dan rancangan
  ini.
