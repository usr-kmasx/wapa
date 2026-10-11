#!/bin/bash
# Instala o wapa no sistema (Arch Linux). Uso: ./install.sh
# Sem conflito com o AppImage: usa app-id/pastas próprios (wapa-sistema).
set -euo pipefail

APP_SYSNAME="wapa-sistema"
APP_ID="local.wapa.sistema"
SRC="$(dirname "$(readlink -f "$0")")"
DEST="/opt/wapa"
BIN="/usr/local/bin/wapa"
DESKTOP="/usr/local/share/applications/${APP_SYSNAME}.desktop"
ICONDIR="/usr/local/share/icons/hicolor/256x256/apps"
DEPS=(python python-gobject gtk4 libadwaita gtk3 libayatana-appindicator)

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== [1/6] Dependências =="
$SUDO pacman -S --needed --noconfirm "${DEPS[@]}"

read -r -p "Instalar a extensão AppIndicator do GNOME (ícone do tray)? [s/N] " ext
if [[ "$ext" =~ ^[sSyY]$ ]]; then
    $SUDO pacman -S --needed --noconfirm gnome-shell-extension-appindicator
    echo "Ative a extensão e reinicie a sessão para ver o tray."
fi

echo "== [2/6] Arquivos em $DEST =="
$SUDO mkdir -p "$DEST"
for f in main.py wallpaper.py wallhaven.py wallhaven_win.py tray.py lang.py; do
    [ -f "$SRC/$f" ] || { echo "FALTANDO: $SRC/$f"; exit 1; }
    $SUDO install -Dm644 "$SRC/$f" "$DEST/$f"
done
if [ -f "$SRC/icon.png" ]; then
    $SUDO install -Dm644 "$SRC/icon.png" "$DEST/icon.png"
elif [ -f "$SRC/icon.jpg" ]; then
    $SUDO install -Dm644 "$SRC/icon.jpg" "$DEST/icon.jpg"
fi

echo "== [3/6] Lançador $BIN =="
$SUDO tee "$BIN" > /dev/null <<EOF
#!/bin/bash
export WAPA_APP_ID=$APP_ID
exec /usr/bin/python3 $DEST/main.py "\$@"
EOF
$SUDO chmod +x "$BIN"

echo "== [4/6] Atalho + ícone =="
$SUDO mkdir -p /usr/local/share/applications "$ICONDIR"
$SUDO tee "$DESKTOP" > /dev/null <<EOF
[Desktop Entry]
Type=Application
Name=wapa
Comment=Trocar wallpaper do GNOME
Comment[pt_BR]=Trocar wallpaper do GNOME
Comment[en_US]=Change GNOME wallpaper
Exec=$BIN
Icon=$APP_SYSNAME
Terminal=false
Categories=GTK;GNOME;Settings;
StartupNotify=true
StartupWMClass=$APP_ID
EOF
$SUDO mkdir -p "$ICONDIR"
if [ -f "$SRC/icon.png" ]; then
    $SUDO install -Dm644 "$SRC/icon.png" "$ICONDIR/$APP_SYSNAME.png"
else
    TMP_PNG="$(mktemp --suffix=.png)"
    python3 -c "
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
src = GdkPixbuf.Pixbuf.new_from_file('$SRC/icon.jpg')
w, h = src.get_width(), src.get_height()
s = 256 / max(w, h)
src.scale_simple(max(1, int(w * s)), max(1, int(h * s)), GdkPixbuf.InterpType.BILINEAR).savev('$TMP_PNG', 'png', [], [])
"
    $SUDO install -Dm644 "$TMP_PNG" "$ICONDIR/$APP_SYSNAME.png"
    rm -f "$TMP_PNG"
fi
$SUDO update-desktop-database /usr/local/share/applications 2>/dev/null || true
$SUDO gtk-update-icon-cache -f -t /usr/local/share/icons/hicolor 2>/dev/null || true

echo "== [5/6] Autoteste =="
python3 -c "
import gi
gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Adw, Gio
Gio.Settings.new('org.gnome.desktop.background')
print('GTK4/Adwaita OK')
"
python3 -c "
import gi
gi.require_version('Gtk', '3.0'); gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, AyatanaAppIndicator3
print('GTK3/tray OK')
"

echo "== [6/6] Pronto! Rode 'wapa' ou abra no menu. =="
