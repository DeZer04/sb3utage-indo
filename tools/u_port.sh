#!/bin/sh
# Rebuild the Utage runtime sources from the Basara ones (commit 1e8781f): hooks moved to Utage
# addresses (u_remap), literal addresses and func_ names (u_dataremap), the hand fixes (u_manual), then
# the Basara 2 leftovers taken out (u_clean).
# Then: tools/u-translate.ps1 -ShardsOnly (or the full translate) and tools/b-win.ps1 -Mode build.
# Files that come out the same as before keep their old modification time, so ninja recompiles only
# what changed (the translated shards include runtime/include: a fresh mtime there rebuilt them all).
set -e
cd "$(dirname "$0")/.."
python -I tools/u_mtimes.py save
git checkout -q 1e8781f -- runtime/src runtime/include
python -I tools/u_remap.py --apply
python -I tools/u_dataremap.py --apply
python -I tools/u_manual.py
python -I tools/u_clean.py
python -I tools/u_mtimes.py restore
