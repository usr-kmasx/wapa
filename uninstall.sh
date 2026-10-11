#!/bin/bash
# Remove COMPLETAMENTE o wapa do sistema. Uso: ./uninstall.sh
# Não toca: pacotes do sistema, ~/Pictures, AppImage, ~/Projects.
set -euo pipefail

APP_SYSNAME="wapa-sistema"
DEST="/opt/wapa"
BIN="/usr/local/bin/wapa"
DESKTOP="/usr/local/share/applications/${APP_SYSNAME}.desktop"
ICON="/usr/local/share/icons/hicolor/256x256/apps/${APP_SYSNAME}.png"
STATE="$HOME/.config/${APP_SYSNAME}"

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== [1/4] Parando o app =="
pkill -f "/opt/wapa/ma[in].py" 2>/dev/null || true
pkill -f "/opt/wapa/tr[ay].py" 2>/dev/null || true
sleep 1

echo "== [2/4] Removendo arquivos =="
$SUDO rm -rf "$DEST" "$BIN" "$DESKTOP" "$ICON"

echo "== [3/4] Removendo configs ($STATE) =="
rm -rf "$STATE"

echo "== [4/4] Atualizando caches =="
$SUDO update-desktop-database /usr/local/share/applications 2>/dev/null || true
$SUDO gtk-update-icon-cache -f -t /usr/local/share/icons/hicolor 2>/dev/null || true

echo "Desinstalado. Pacotes do sistema foram mantidos de propósito."
