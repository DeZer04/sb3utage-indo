# Kebijakan Keamanan

*English: report vulnerabilities privately through GitHub's "Report a vulnerability" button on the Security tab, not in a public issue. Only the latest release is supported.*

## Versi yang didukung

Perbaikan keamanan hanya dibuat untuk **rilis terbaru** di halaman [Releases](https://github.com/DeZer04/sb3utage-indo/releases). Build uji (dev) dan versi lama tidak mendapat perbaikan. Silakan perbarui ke rilis terbaru.

## Yang termasuk cakupan

Masalah pada aplikasi SB3 UTAGE:INDO dan infrastrukturnya, misalnya:

- pemasangan patch terjemahan (file `.patch`, katalog [`patches.json`](https://github.com/DeZer04/sb3utage-indo/blob/main/patches.json), dan unduhannya);
- cara aplikasi membaca file dari penyimpanan HP: dump game, mod tekstur, save, dan log;
- fitur jaringan aplikasi dan driver GPU custom yang dipasang pengguna;
- situs <https://dezer04.github.io/sb3utage-indo/> dan patcher di browser.

Yang **tidak** termasuk: bug biasa seperti crash, grafis, atau performa. Untuk itu, buat [issue biasa](https://github.com/DeZer04/sb3utage-indo/issues/new/choose).

## Melaporkan celah keamanan

**Jangan melaporkan celah keamanan lewat issue, pull request, atau Discussions publik.**

1. Buka tab [Security](https://github.com/DeZer04/sb3utage-indo/security) di repository ini, lalu pilih **Report a vulnerability**. Laporan itu hanya terlihat oleh pengelola.
2. Tuliskan:
   - versi aplikasi dan HP yang dipakai;
   - langkah untuk mengulang masalahnya;
   - dampak yang mungkin terjadi.

   Sertakan contoh file seperlunya saja, dan **jangan pernah mengirim file game**.

Pengelola akan menanggapi secepatnya dan memberi kabar perkembangan perbaikannya. Setelah perbaikan dirilis, pelapor akan dicantumkan di catatan rilis, kecuali ingin tetap anonim.

## Tips aman untuk pemain

- Pasang APK **hanya** dari halaman [Releases](https://github.com/DeZer04/sb3utage-indo/releases) repository ini. Nama aplikasi resminya **SB3 UTAGE:INDO** dengan package id `io.github.dezer04.sb3utage`. APK dari tempat lain bisa saja sudah diubah.
- Patch terjemahan yang diunduh dari dalam aplikasi dicek dengan sha256 dari `patches.json` sebelum dipasang.
