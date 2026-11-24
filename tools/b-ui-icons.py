# Writes the launcher's line icons (24x24, Feather-style strokes) as Android vector drawables.
# Usage: python -I tools/b-ui-icons.py   (output: app/src/main/res/drawable/ic_*.xml)
import pathlib

ICONS = {
    "display": "M4,3h16a2,2 0 0,1 2,2v10a2,2 0 0,1 -2,2H4a2,2 0 0,1 -2,-2V5a2,2 0 0,1 2,-2z M8,21h8 M12,17v4",
    "graphics": "M5,3h14a2,2 0 0,1 2,2v14a2,2 0 0,1 -2,2H5a2,2 0 0,1 -2,-2V5a2,2 0 0,1 2,-2z "
                "M10,8.5a1.5,1.5 0 1,1 -3,0a1.5,1.5 0 1,1 3,0z M21,15l-5,-5L5,21",
    "performance": "M22,12h-4l-3,9L9,3l-3,9H2",
    "controls": "M8,6h8a6,6 0 0,1 0,12H8a6,6 0 0,1 0,-12z M6,12h4 M8,10v4 M15,11h0.01 M17,13h0.01",
    "save": "M19,21H5a2,2 0 0,1 -2,-2V5a2,2 0 0,1 2,-2h11l5,5v11a2,2 0 0,1 -2,2z M17,21v-8H7v8 M7,3v5h8",
    "cheats": "M13,2L3,14h9l-1,8l10,-12h-9l1,-8z",
    "system": "M4,21v-7 M4,10V3 M12,21v-9 M12,8V3 M20,21v-5 M20,12V3 M1,14h6 M9,8h6 M17,16h6",
    "move": "M5,9l-3,3l3,3 M9,5l3,-3l3,3 M15,19l-3,3l-3,-3 M19,9l3,3l-3,3 M2,12h20 M12,2v20",
    "folder": "M22,19a2,2 0 0,1 -2,2H4a2,2 0 0,1 -2,-2V5a2,2 0 0,1 2,-2h5l2,3h9a2,2 0 0,1 2,2z",
}
FILLED = {"play": "M6,4l14,8l-14,8z"}

out = pathlib.Path(__file__).resolve().parents[1] / "app/src/main/res/drawable"
out.mkdir(parents=True, exist_ok=True)
head = ('<?xml version="1.0" encoding="utf-8"?>\n'
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="24dp" android:height="24dp" android:viewportWidth="24" android:viewportHeight="24">\n')
for name, d in ICONS.items():
    (out / f"ic_{name}.xml").write_text(
        head + f'    <path android:pathData="{d}" android:strokeColor="#FFFFFFFF" android:strokeWidth="1.75"\n'
        '        android:strokeLineCap="round" android:strokeLineJoin="round" android:fillColor="#00000000" />\n'
        '</vector>\n', encoding="utf-8", newline="\n")
for name, d in FILLED.items():
    (out / f"ic_{name}.xml").write_text(
        head + f'    <path android:pathData="{d}" android:fillColor="#FFFFFFFF" android:strokeColor="#FFFFFFFF"\n'
        '        android:strokeWidth="1.5" android:strokeLineJoin="round" />\n</vector>\n',
        encoding="utf-8", newline="\n")
print(len(ICONS) + len(FILLED), "icons ->", out)
