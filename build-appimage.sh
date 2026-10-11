#!/bin/bash
# Rebuild do AppImage com os fontes atuais (atualização cirúrgica:
# mantém o runtime do bundle — python 3.14 + GTK — e troca só o app).
# Uso: ./build-appimage.sh  (gera wapa-x86_64.AppImage ao lado)
# Requer: curl (baixa o appimagetool na 1ª vez, em /tmp/opencode).
set -euo pipefail

SRC="$(dirname "$(readlink -f "$0")")"
OUT="$SRC/wapa-x86_64.AppImage"
WORK=/tmp/opencode/apibuild
APPIMG=$WORK/appimagetool.AppImage
PY_SOURCES=(lang.py main.py tray.py wallhaven.py wallhaven_win.py wallpaper.py)

mkdir -p "$WORK"
if [ ! -x "$APPIMG" ]; then
    echo "== baixando appimagetool =="
    curl -sSL -o "$APPIMG" \
      https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$APPIMG"
fi
if [ ! -x "$WORK/ait/AppRun" ]; then
    echo "== extraindo appimagetool =="
    rm -rf "$WORK/ait"
    mkdir -p "$WORK/ait" && cd "$WORK/ait"
    "$APPIMG" --appimage-extract >/dev/null
    cd "$SRC"
fi
AIT="$WORK/ait/squashfs-root/AppRun"

echo "== extraindo AppImage atual =="
rm -rf "$WORK/build"
mkdir -p "$WORK/build" && cd "$WORK/build"
"$OUT" --appimage-extract >/dev/null
mv squashfs-root appdir

echo "== atualizando fontes =="
for f in "${PY_SOURCES[@]}"; do
    [ -f "$SRC/$f" ] || { echo "FALTANDO: $SRC/$f"; exit 1; }
    cp "$SRC/$f" "appdir/usr/share/wapa/$f"
done
APPDIR_BIN="$PWD/appdir/usr/bin/python3.14"
"$APPDIR_BIN" -m py_compile appdir/usr/share/wapa/*.py && echo "compile OK (bundled python)"

echo "== empacotando =="
"$AIT" "$PWD/appdir" "$OUT"
chmod +x "$OUT"
ls -la "$OUT"
echo "Pronto: $OUT"
