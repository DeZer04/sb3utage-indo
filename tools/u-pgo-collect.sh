#!/usr/bin/env bash
# Collects the PGO counters the instrumented app (SB3 UTAGE PGO, scratchpad apk_pgo.ps1) wrote on a phone
# and merges every phone's into the profile the release build uses.
#   bash tools/u-pgo-collect.sh pull SERIAL NAME   every SB3UtageINDO/Logs/*/log/libmain.profraw on the phone
#                                                  -> generated/b/pgo/raw/NAME_<run>.profraw (gzip over adb)
#   bash tools/u-pgo-collect.sh merge [NAME=W ...] all raw profiles -> generated/b/pgo/libmain_<date>.profdata, a
#                                                  phone's runs weighted W (a slow phone runs few frames:
#                                                  a54=5 lets its 30 FPS Lock and catch-up paths count)
# Then: powershell -File tools\u-apk.ps1 -Version X -Code N -Profile <that profdata> (a new file name, so every
# object is rebuilt with it).
set -eu
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
ADB=${ADB:-E:/Installers/andr_1/platform-tools/adb.exe}
PROFDATA=${PROFDATA:-E:/Installers/andr_1/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-profdata.exe}
RAW=generated/b/pgo/raw
mkdir -p "$RAW"
case "${1:-}" in
pull)
    serial=$2; name=$3
    files=$("$ADB" -s "$serial" shell 'ls /sdcard/SB3UtageINDO/Logs/*/log/libmain.profraw 2>/dev/null' | tr -d '\r')
    [ -n "$files" ] || { echo "no libmain.profraw on $serial"; exit 1; }
    for f in $files; do
        run=$(echo "$f" | sed -E 's|.*/Logs/([^/]+)/log/.*|\1|')
        out="$RAW/${name}_${run}.profraw"
        [ -s "$out" ] && { echo "have $out"; continue; }
        "$ADB" -s "$serial" exec-out "gzip -c -1 '$f'" > "$out.gz"
        gzip -d -f "$out.gz"
        echo "pulled $out ($(du -h "$out" | cut -f1))"
    done
    ;;
merge)
    shift
    ls "$RAW"/*.profraw >/dev/null
    out=generated/b/pgo/libmain_$(date +%Y%m%d-%H%M).profdata
    inputs=()
    for f in "$RAW"/*.profraw; do
        w=1
        for spec in "$@"; do
            case "$(basename "$f")" in "${spec%%=*}"_*) w=${spec#*=} ;; esac
        done
        inputs+=("-weighted-input=$w,$f")
    done
    "$PROFDATA" merge -o "$out" "${inputs[@]}"
    "$PROFDATA" show "$out" | tail -3
    echo "$out"
    ;;
*)
    sed -n 2,9p "$0"; exit 1
    ;;
esac
