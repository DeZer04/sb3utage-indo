# Cara Berkontribusi

Terima kasih sudah mau membantu SB3 UTAGE:INDO. Laporan dari HP kamu (berjalan lancar atau tidak), koreksi terjemahan, dan perbaikan kode semuanya berguna. Sebelum ikut serta, baca [Kode Etik](CODE_OF_CONDUCT.md).

*English: bug reports, device reports, translation fixes and code are all welcome. Issues and discussions can be written in Indonesian or English. Start with the templates on the New issue page; attach the zip from Settings > System > Share Log to any bug report.*

## Mau ngapain?

| Kamu ingin... | Tempatnya |
|---|---|
| Melaporkan crash, freeze, grafis rusak, atau bug lain | [Issue baru → Laporan bug](https://github.com/DeZer04/sb3utage-indo/issues/new/choose) |
| Melaporkan teks yang salah, typo, atau terjemahan aneh | [Issue baru → Kesalahan terjemahan](https://github.com/DeZer04/sb3utage-indo/issues/new/choose) |
| Mengusulkan fitur | [Issue baru → Usul fitur](https://github.com/DeZer04/sb3utage-indo/issues/new/choose) atau [Discussions → Ideas](https://github.com/DeZer04/sb3utage-indo/discussions/categories/ideas) |
| Bertanya cara pasang, pengaturan, atau patch | [Discussions → Q&A](https://github.com/DeZer04/sb3utage-indo/discussions/categories/q-a) |
| Membagikan hasil di HP kamu (FPS, pengaturan) | [Discussions → Show and tell](https://github.com/DeZer04/sb3utage-indo/discussions/categories/show-and-tell) |
| Melaporkan celah keamanan | Jangan lewat issue publik. Lihat [Kebijakan Keamanan](SECURITY.md). |

## Melaporkan bug

1. Pastikan kamu memakai versi terbaru dari halaman [Releases](https://github.com/DeZer04/sb3utage-indo/releases). Bug di versi lama mungkin sudah diperbaiki.
2. Cari dulu di [issue yang sudah ada](https://github.com/DeZer04/sb3utage-indo/issues?q=is%3Aissue). Kalau masalahnya sama, tambahkan log dan info HP kamu di sana.
3. Di aplikasi, buka **Pengaturan > Sistem > Share Log**, lalu pilih sesi yang bermasalah (sesi yang crash otomatis ada di urutan pertama). Hasilnya satu file zip.
4. Buat issue dengan template **Laporan bug** dan lampirkan zip itu. Tulis apa yang kamu lakukan sebelum masalahnya muncul: mode, stage, adegan, dan pengaturan yang baru diubah.

Log ada juga di HP, satu folder per sekali buka game: `SB3UtageINDO/Logs/<tanggal dan jam>/`.

Yang paling membantu:

- **Satu masalah per issue.**
- **Langkah untuk mengulang** masalahnya, kalau bisa.
- **Screenshot atau rekaman layar** untuk masalah grafis.
- **Ulangi di pengaturan bawaan** (Pengaturan > Reset), supaya kelihatan apakah masalahnya ikut pengaturan tertentu.

## Laporan HP (berjalan lancar juga dihitung)

Daftar "Tested phones" di README terisi dari laporan pemain. Kalau HP kamu belum ada, atau hasilnya berbeda, buat postingan di [Show and tell](https://github.com/DeZer04/sb3utage-indo/discussions/categories/show-and-tell) dengan template yang tersedia, sertakan zip Share Log.

## Koreksi terjemahan

Laporkan lewat template **Kesalahan terjemahan**: tulis di mana teks itu muncul, teks yang tampil, dan usulan perbaikannya, lalu sertakan screenshot. Nama tokoh dan istilah mengikuti glosarium project, jadi perubahan nama yang sudah baku akan didiskusikan dulu.

Tekstur Indonesia di patch **Full Indo + Tekstur Sin-Nohara** adalah karya Sin-Nohara. Masukan untuk tekstur itu akan diteruskan kepada pembuatnya.

## Kontribusi kode

1. Fork repository ini, lalu buat branch dari `main`.
2. Cara build ada di bagian [Building](https://github.com/DeZer04/sb3utage-indo#building) di README.
3. Buat pull request ke `main` dan isi template-nya. Sebutkan HP yang kamu pakai untuk tes.

Aturan penting:

- **`runtime/src` adalah hasil generate.** Kode di sana dibuat ulang dari port asal, jadi perbaikan untuk runtime ditulis sebagai entri di `tools/u_manual.py`. Jangan menyunting `runtime/src` langsung, karena perubahannya akan hilang saat dibuat ulang.
- **Jangan memasukkan aset atau kode game.** Ini termasuk ISO/RVZ, file dari disc, hasil dump tekstur, dan potongan kode PowerPC asli. Repository ini tidak berisi aset game, dan harus tetap begitu.
- **Satu perubahan per pull request.** Jelaskan *kenapa* perubahan itu perlu, bukan hanya *apa* yang diubah.
- **Ikuti gaya kode di sekitarnya**, termasuk penamaan dan kepadatan komentar.
- Teks antarmuka aplikasi ditulis dalam bahasa Inggris dan diterjemahkan di `app/src/main/assets/lang/id.txt`. Tambahkan terjemahan Indonesia untuk setiap teks baru.

## Lisensi

Kode project ini berlisensi [GPL-3.0](https://github.com/DeZer04/sb3utage-indo/blob/main/LICENSE). Dengan mengirim kontribusi, kamu setuju kontribusimu dirilis dengan lisensi yang sama. Pihak ketiga tercantum di [THIRD-PARTY-NOTICES.md](https://github.com/DeZer04/sb3utage-indo/blob/main/THIRD-PARTY-NOTICES.md).

*Sengoku Basara* beserta tokoh dan logonya adalah milik Capcom. Project ini adalah proyek penggemar yang tidak resmi.
