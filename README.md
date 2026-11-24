# SB3 UTAGE:INDO

An unofficial port of *Sengoku Basara 3 Utage* (Wii, NTSC-J, `S3HJ08`) to Android (arm64), with an Indonesian translation.

The game's PowerPC code is recompiled to C++ ahead of time on a PC and built into a native app, together with a runtime that stands in for the Wii's system software and a GX renderer on Vulkan. Nothing is emulated on the phone.

> [!NOTE]
> This repository contains no game assets and no game code. You need a dump of your own legally acquired disc.
>
> This is an unofficial fan project, not affiliated with or endorsed by Capcom. Sengoku Basara, its characters and its logo belong to Capcom.

### Ringkasan (Bahasa Indonesia)

**SB3 UTAGE:INDO** adalah port tidak resmi *Sengoku Basara 3 Utage* (Wii, Jepang, `S3HJ08`) untuk Android (arm64). Kode game dikompilasi ulang menjadi aplikasi native, jadi tidak ada emulator yang berjalan di HP.

- **Kebutuhan:** Android 10 ke atas (arm64) dan dump disc milikmu sendiri (`.iso` atau `.rvz`, `S3HJ08`). Vulkan disarankan.
- **Unduh** APK hanya dari halaman [Releases](../../releases) repository ini.
- **Terjemahan Indonesia** teks game: di halaman awal aplikasi, pilih **Full Patch Indo** atau **Deskripsi Only** lalu **Pasang**. Keduanya bisa diunduh langsung di aplikasi (daftar [`patches.json`](patches.json)); file `.patch` lain dipasang dari folder Download atau `SB3UtageINDO/Patch`. Ganti ke Jepang asli kapan saja tanpa pasang ulang (Pengaturan > Sistem > Patch Terjemahan).
- **Pengaturan** ada di menu dalam game (tombol Back atau ikon roda gigi), dalam bahasa Inggris dan Indonesia.
- **Ada masalah?** Pengaturan > Sistem > **Share Log**, lalu lampirkan di [GitHub issue](../../issues) baru (lihat [Reporting a problem](#reporting-a-problem)).

**Contents:** [Status](#status) · [Features](#features) · [Getting started](#getting-started) · [Saves](#saves) · [Reporting a problem](#reporting-a-problem) · [Patch catalog](#patch-catalog-patchesjson) · [Building](#building) · [Credits](#credits) · [License](#license)

## Status

**Current release: [1.0.3](../../releases)** (November 2026). The game plays on Android from boot through the menus, Story, Free Battle and Unification (Penyatuan Negeri), with sound, saving and loading. What changed in each version is on the [Releases](../../releases) page and in the app under **What's New**.

Known limits:

- The first start after installing or updating builds the game's shaders in the background (a few minutes, a counter in the corner shows how far); some effects can appear a moment late until it finishes.
- Busy battles can drop below 30 FPS on slower phones: the game's own code is the limit there. The presets, 30 FPS Lock and GX Thread help.
- The Wii HOME Menu is not available (its button is hidden).

### Tested phones

Results from our own phone and from testers' logs. "Version" is the build it was last tested on.

| Phone | Chip / GPU | Android | Battles | Version |
|---|---|---|---|---|
| Poco X6 5G | Snapdragon 7s Gen 2 / Adreno 710 | 16 | 45–60 fps at 1x render resolution, 40–52 at 1.5x in busy battles; Game Speed 150% holds 1.47–1.50x; the recorder at 720p 60 FPS | 1.0.1 |
| Poco X7 Pro | Dimensity 8400 Ultra / Mali-G720 MC7 | 16 | 47 fps median at 2x render resolution over a 28-minute session, lowest 10-second average 29 (a profiling build, slower than the release) | 1.0.0 |
| Infinix GT 10 Pro (X6739) | Dimensity 8050 / Mali-G77 MC9 | 14 | 50–58 fps median at 1.5x render resolution | 0.5.x |
| Infinix X6882 | Helio G99 / Mali-G57 MC2 | | 25–36 fps in busy battles with GX Thread | 0.5.x |
| OPPO A54 | Helio P35 / PowerVR GE8320 | 11 | Playable on the Low preset (0.5x, 30 FPS Lock, dynamic resolution): about 15 fps in busy battles, where the CPU is the limit | 1.0.0 |

Your phone is not here, or runs differently? Send a Share Log (see [Reporting a problem](#reporting-a-problem)), working or not: these reports are what fills this list.

## Features

| Area | What it has |
|---|---|
| **In-game menu** | Every setting is in the game's menu (Back, or the gear): Display, Graphics, Performance, Controls, Save Data, Textures and System. English and Indonesian. |
| **Performance** | Presets (Extreme Low, Low, Default, Medium, High), **Game Speed** (110–200%), Frameskip, 30 FPS Lock, V-Sync, Dynamic Resolution, GX Thread, Thermal Control, Sustained Performance, Disable Fog, Reduce Effects (Experimental), Upload Memory. A device profile picks the settings on first start. |
| **Shaders** | No waiting screen: shaders build in the background on the phone's small cores while you play, are kept on the phone (translated shaders and the driver's own cache) and load only when a scene needs them. |
| **Graphics** | Renderer (Auto, Vulkan, WebGPU 1.2, OpenGL ES (Experimental)), Render and Display Resolution, upscalers, Texture Detail, Graphics Compatibility for GPUs whose drivers break the models, custom GPU drivers. |
| **Display** | Aspect Ratio (4:3, 16:9, Fill Screen), Camera Distance for a wider battle view, Lock Target (Experimental), Performance Overlay (Bar or Minimal, chosen items, frame-time graph). |
| **Controls** | On-screen Classic Controller with one icon per move, a layout editor and opacity, touch camera, LOCK and zoom buttons; gamepads in the Classic Controller layout with remappable buttons. |
| **Textures** | Texture mods (.png or .dds, Dolphin names) in their own folders, ticked and ordered in the Textures tab; texture dumping, texture key reports, HD Textures. |
| **Tools** | Save backup and import, Share Log, Device Info, Reset and Clear, What's New. |

## Getting started

**Requirements:** Android 10 or newer, arm64. Vulkan is recommended; OpenGL ES is available as an experimental renderer.

1. Install the APK from this repository's [latest release](../../releases). Do not use APKs from anywhere else.
2. Open the app and allow file access when asked (the logs, saves and texture mods live in `SB3UtageINDO/` on the phone).
3. Pick your own dump of the game (`.iso` or `.rvz`, Wii NTSC-J `S3HJ08`). Unpack it once (about 4 GB) or play it straight from the file; after that the app opens on its first page: the game's details, the translation patches and Play.
4. The first start chooses settings for your phone and builds the shaders in the background. Change any setting from the game's menu (Back, or the gear).

**Indonesian translation:** the game's own text (dialogue, menus) comes as a `.patch` file (only the differences from the original disc, about 112 MB for the full patch). On the app's first page choose **Full Patch Indo** or **Deskripsi Only** and **Install**: the patch is built from your own dump, whether the app reads the ISO/RVZ or unpacked it, into `SB3UtageINDO/Riivolution/<patch>`; your game file is not changed. Each patch keeps its own folder, so switching between Indonesian and the original Japanese is instant, on the first page or in Settings > System > **Translation Patch** (after Restart). A Riivolution package copied by hand into `SB3UtageINDO/Riivolution` (its `riivolution` and `S3HJ08` folders) shows up there too.

**Updates:** new versions are posted on [Releases](../../releases). Installing a new version over the old one keeps your save and settings.

## Saves

The save lives in the app's own storage. In **Settings > Save Data**:

- **Back Up** writes `sb3utage-save-DATE.zip` to `SB3UtageINDO/Saves`. Copy it to a PC or cloud drive to keep it safe.
- **Import** replaces the save on the phone. It accepts:
  - a `.zip` made by Back Up,
  - a bare `save_h.bin`,
  - a `data.bin` copied to SD from a Wii (Data Management) or exported by Dolphin (Export Wii Save).
- **Undo Last Import** brings back the save from before the last import. An automatic backup is kept in `SB3UtageINDO/Saves/Auto` before every import.

## Reporting a problem

In the app, Settings > System > **Share Log** puts the logs of the runs you pick (the crashed one first) and your device info in one zip. Attach it, with what you were doing, to a new [GitHub issue](../../issues).

The logs are also on the phone, one folder per game start: `SB3UtageINDO/Logs/<date and time>/`.

## Patch catalog (`patches.json`)

The app reads [`patches.json`](patches.json) from this repository's `main` branch to offer translation patches for download and to show "update available" when a newer version is listed:

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

`id` is `full` or `desc` (the app names and describes these itself), or a new id with its own `name` and `description`. To release a patch, upload the `.patch` (made with `tools/u_make_patch.py`, checked with `tools/u_check_patch.py`) to a release and raise `version`, `url`, `size` and `sha256` here. App updates come from the releases themselves (pre-releases included): the APK asset must end in `-android-arm64.apk`, and the release's version must be higher than the installed one.

## Building

For developers. Requires Windows with Git Bash and Python 3, .NET 8, llvm-mingw in `third_party/llvm-mingw` (Windows build) and Android NDK 28.2 (fetched by `tools/setup-android.ps1`).

The Utage runtime sources are generated: `tools/u_port.sh` checks out the Sengoku Basara 2 Heroes runtime this port started from, moves its hooks to Utage's addresses (`tools/u_remap.py`, `tools/u_dataremap.py`) and applies the Utage changes in `tools/u_manual.py`. Change `tools/u_manual.py`, never `runtime/src` by hand.

```powershell
# Copy main.dol from your disc to assets/utage/sys/main.dol, then:
tools\setup-android.ps1               # toolchain and dependencies (third_party/)
sh tools/u_port.sh                    # runtime/src for Utage
tools\u-translate.ps1                 # PowerPC -> C++ (generated/); -ShardsOnly after adding a native override
tools\b-win.ps1 -Mode configure       # once
tools\b-win.ps1 -Mode build           # Windows build, for testing on a PC
tools\b-android.ps1 -Mode configure -Ndk <NDK 28.2>   # once
tools\b-android.ps1 -Mode build -Ndk <NDK 28.2>       # libmain.so
tools\b-android.ps1 -Mode stage -Ndk <NDK 28.2>
cd app
gradle assembleRelease "-PbasaraVersionName=1.0.0" "-PbasaraVersionCode=56" "-PbasaraSigning=<signing.properties>"
# In PowerShell quote each -P...=x.y.z, or the version splits.
```

Release builds use profile-guided optimization with ThinLTO (`tools\b-pgo.ps1`): record a profile with an instrumented build while playing busy battles, then build with it.

| Path | Contents |
|---|---|
| `app/` | Android app (Gradle module): launcher, in-game menu, settings, touch controls |
| `runtime/` | Host runtime and Wii SDK HLE (OS, GX, AX, NAND/DVD, VI), performance overlay; `runtime/src` is generated by `tools/u_port.sh` |
| `aurora/` | GX renderer on WebGPU (Dawn), native Vulkan and OpenGL ES |
| `translator/` | PowerPC-to-C++ translator (C#/.NET 8) |
| `config/utage/` | Game configuration: `recomp.yml`, `MAP.txt` |
| `assets/` | `utage/sys/main.dol` (yours, not in git) and `pipeline/`, the bundled shader list |
| `tools/` | Build, run and analysis scripts (`u_*` for Utage) |

## Credits

This project is a modified version of the *Sengoku Basara 2 Heroes* port by xu@shiinobu, itself a modified version of NSMB-Wii-Multiplayer-Recompilation, which is built on WiiCompiled. It was changed from November 2026 to run *Sengoku Basara 3 Utage*.

- **DeZer04**: the Sengoku Basara 3 Utage port and the Indonesian translation.
- **xu@shiinobu**: the Sengoku Basara 2 Heroes port this one is built on.
- **hikki@datfooldive**: the menu and touch button design.
- **[NSMB-Wii-Multiplayer-Recompilation](https://github.com/WitherBlitz/NSMB-Wii-Multiplayer-Recompilation)** by WitherBlitz: the Android app and the runtime the ports started from.
- **[WiiCompiled](https://github.com/patchzyy/Wiicompiled)** by patchzyy and contributors: the static recompiler and runtime underneath it.
- **[Jude (@YlPorts)](https://github.com/YlPorts)**: the Android draw-count and Mali GPU changes.
- **[KartPad](https://github.com/chrissotraidis/kartpad)**: WiiCompiled on Android, whose approach and game-file import steps the ports follow.
- **[aurora](https://github.com/encounter/aurora)** by Luke Street: the GX rendering and windowing backend.
- **[Dawn](https://dawn.googlesource.com/dawn)**: Google's WebGPU implementation, used by aurora.
- **[Dolphin Emulator](https://github.com/dolphin-emu/dolphin)**: the reference for Wii hardware behavior and renderer techniques, the free DSP coefficient ROM and the default WiiConnect24 tree in the runtime, the RVZ format the app reads, and the Wii save (`data.bin`) format.
- **The NSMBW reverse-engineering community**: RootCubed's [NSMBW symbols](https://github.com/RootCubed/nsmbw-symbols), the NSMBW decompilation and the NSMBW address maps, where the function maps started.
- **[game-icons.net](https://game-icons.net)** by Lorc, Delapouite and contributors (CC BY 3.0): the touch control icons.
- **[Roboto](https://fonts.google.com/specimen/Roboto)** by Google (Apache 2.0): the performance overlay's font.
- **[DriftDroid](https://github.com/dorPXP/driftdroid)** and **[Galaxy-Android](https://github.com/OpenPort-Labs/Galaxy-Android)**: other Wii-to-Android ports, read for reference.
- Coded with Claude (Anthropic).

Bundled third-party components and their licenses are listed in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).

## License

GPLv3, see [`LICENSE`](LICENSE) and [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md). APKs are published only on this repository's [Releases](../../releases) page; the source of each APK is this repository at that release's tag. The app carries the same `LICENSE` and notices (Settings > System > Source Code & License).

This program comes with ABSOLUTELY NO WARRANTY. It is free software: you may redistribute and change it under the terms of the GNU General Public License, version 3.
