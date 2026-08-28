#!/usr/bin/env bash
# Remove serviços, autostart e permissões do Zee Assistant.
# Não apaga o diretório do projeto nem os dados (recursos.json, logs, modelo).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ZEE_USER="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "${ZEE_USER}" | cut -d: -f6)"

echo "==> Removendo o Zee Assistant (o diretório do projeto será preservado)"
read -r -p "    Confirmar? [s/N] " answer
[ "${answer,,}" = "s" ] || { echo "    Cancelado."; exit 0; }

echo "==> Parando serviços"
sudo systemctl disable --now zee-assistant.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/zee-assistant.service
sudo systemctl daemon-reload
echo "  ✔ systemd limpo"

echo "==> Removendo autostart do kiosk"
rm -f "${USER_HOME}/.config/autostart/zee-kiosk.desktop"
[ -f "${USER_HOME}/.config/labwc/autostart" ] && sed -i "\|scripts/kiosk.sh|d" "${USER_HOME}/.config/labwc/autostart" || true
[ -f "${USER_HOME}/.config/wayfire.ini" ] && sed -i "/zee_kiosk/d" "${USER_HOME}/.config/wayfire.ini" || true
echo "  ✔ autostart removido"

echo "==> Removendo permissões e captive portal"
sudo rm -f /etc/sudoers.d/zee-assistant
sudo rm -f /etc/NetworkManager/dnsmasq-shared.d/zee-captive.conf
sudo nmcli connection delete zee-setup-ap 2>/dev/null || true
echo "  ✔ permissões removidas"

echo "==> Concluído."
echo "    Para remover também o código:  rm -rf ${ZEE_DIR}"
echo "    Para remover o virtualenv:     rm -rf ${ZEE_DIR}/venv"
