# SB3 UTAGE:INDO

Aplikasi Android untuk memainkan **Sengoku BASARA 3 Utage** (Wii, Jepang, `S3HJ08`) dengan patch terjemahan Bahasa Indonesia.

> Game **tidak** disertakan. Pakai file ISO/RVZ dari disc milikmu sendiri.

## Unduh

Buka halaman [Releases](https://github.com/DeZer04/sb3utage-indo/releases) dan unduh `sb3utage-indo-<versi>-android-arm64.apk`.

- Android 10 ke atas, HP 64-bit (arm64)
- Ruang kosong sekitar 4,5 GB kalau game diekstrak

## Cara pakai

1. Pasang APK lalu buka. Izinkan akses file saat diminta.
2. Pilih file game (ISO/RVZ `S3HJ08`):
   - **Ekstrak**: game dibongkar sekali (sekitar 4 GB). Loading paling cepat.
   - **Baca dari File**: game dibaca langsung dari file ISO/RVZ.
3. Di halaman pertama, pilih patch terjemahan lalu pasang.
4. Tekan **Main**.

Bahasa aplikasi bisa diganti di halaman pertama (Bahasa Indonesia / English).

## Patch terjemahan

| Patch | Isi | Cara dapat |
|---|---|---|
| Tanpa Patch | Game asli bahasa Jepang | — |
| Full Patch Indo | Seluruh game: menu, cerita, item, dan deskripsi | File `.patch` dibagikan terpisah |
| Deskripsi Only | Hanya nama dan deskripsi item, perlengkapan, senjata, jurus, dan kemampuan; sisanya tetap Jepang | Unduh langsung di aplikasi |

- Patch dibuat dari file game milikmu sendiri. Tiap patch punya folder sendiri, jadi ganti antara Bahasa Indonesia dan Jepang asli langsung bisa.
- File `.patch` yang ada di HP (folder `Download` atau `SB3UtageINDO/Patch`) muncul sendiri di daftar. Bisa juga lewat **Pilih File .patch**.
- Di dalam game: Pengaturan > Sistem > Patch Terjemahan (berlaku setelah Mulai Ulang).

## Update

- **Aplikasi**: saat dibuka, aplikasi mengecek rilis terbaru di halaman ini (termasuk pre-release) dan menawarkan update. Cek manual: Pengaturan > Sistem > Cek Update. Save dan pengaturan tetap aman.
- **Patch**: daftar patch dibaca dari [`patches.json`](patches.json). Kalau ada versi yang lebih baru dari yang terpasang, muncul tulisan "update tersedia" dan tombol Update.

### Format `patches.json`

```json
{
  "patches": [
    {
      "id": "desc",
      "version": "1.0",
      "url": "https://github.com/DeZer04/sb3utage-indo/releases/download/v1.0.0/SB3U-INDO-Desc-v1.0.patch",
      "size": 205958,
      "sha256": "c71a19dcce85cd79a8c0404ca870e5dbcec233e5ca691b934915c2188fd0cfc4"
    }
  ]
}
```

`id`: `full` atau `desc` (atau id baru, dengan `name` dan `description`). Untuk merilis patch baru, unggah file `.patch` ke sebuah release lalu naikkan `version`, `url`, `size`, dan `sha256` di sini.
