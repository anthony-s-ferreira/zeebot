#!/usr/bin/env bash
# Configura a inicialização automática do Chromium em modo kiosk.
# Detecta a sessão gráfica (labwc / wayfire / X11) do Raspberry Pi OS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ZEE_USER="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "${ZEE_USER}" | cut -d: -f6)"
KIOSK="${ZEE_DIR}/scripts/kiosk.sh"

ok()   { echo "  ✔ $*"; }
warn() { echo "  ! $*"; }

chmod +x "${KIOSK}"
run_as_user() { sudo -u "${ZEE_USER}" "$@"; }

echo "==> Configurando kiosk para o usuário ${ZEE_USER} (${USER_HOME})"

# 1) XDG autostart — funciona em LXDE/X11 e em várias sessões Wayland.
AUTOSTART_DIR="${USER_HOME}/.config/autostart"
run_as_user mkdir -p "${AUTOSTART_DIR}"
cat <<EOF | sudo tee "${AUTOSTART_DIR}/zee-kiosk.desktop" >/dev/null
[Desktop Entry]
Type=Application
Name=Zee Assistant Kiosk
Comment=Abre o Zee Assistant em tela cheia
Exec=${KIOSK}
X-GNOME-Autostart-enabled=true
NoDisplay=false
Terminal=false
EOF
sudo chown "${ZEE_USER}:${ZEE_USER}" "${AUTOSTART_DIR}/zee-kiosk.desktop"
ok "autostart XDG instalado em ${AUTOSTART_DIR}/zee-kiosk.desktop"

# 2) labwc (Raspberry Pi OS Bookworm recente)
if command -v labwc >/dev/null 2>&1; then
  LABWC_DIR="${USER_HOME}/.config/labwc"
  run_as_user mkdir -p "${LABWC_DIR}"
  AUTOSTART_FILE="${LABWC_DIR}/autostart"
  sudo touch "${AUTOSTART_FILE}"
  if ! sudo grep -q "zee/scripts/kiosk.sh\|${KIOSK}" "${AUTOSTART_FILE}" 2>/dev/null; then
    echo "${KIOSK} &" | sudo tee -a "${AUTOSTART_FILE}" >/dev/null
  fi
  sudo chown -R "${ZEE_USER}:${ZEE_USER}" "${LABWC_DIR}"
  ok "labwc autostart configurado"
fi

# 3) wayfire (Raspberry Pi OS Bookworm inicial)
WAYFIRE_INI="${USER_HOME}/.config/wayfire.ini"
if command -v wayfire >/dev/null 2>&1 || [ -f "${WAYFIRE_INI}" ]; then
  sudo touch "${WAYFIRE_INI}"
  if ! sudo grep -q "^\[autostart\]" "${WAYFIRE_INI}"; then
    printf '\n[autostart]\n' | sudo tee -a "${WAYFIRE_INI}" >/dev/null
  fi
  if ! sudo grep -q "zee_kiosk" "${WAYFIRE_INI}"; then
    sudo sed -i "/^\[autostart\]/a zee_kiosk = ${KIOSK}" "${WAYFIRE_INI}"
  fi
  # desliga o apagamento de tela
  if ! sudo grep -q "^\[idle\]" "${WAYFIRE_INI}"; then
    printf '\n[idle]\ndpms_timeout = -1\nscreensaver_timeout = -1\n' | sudo tee -a "${WAYFIRE_INI}" >/dev/null
  fi
  sudo chown "${ZEE_USER}:${ZEE_USER}" "${WAYFIRE_INI}"
  ok "wayfire.ini configurado (autostart + sem blanking)"
fi

# 4) LXDE/X11: desliga screensaver e blanking
LXDE_AUTOSTART="${USER_HOME}/.config/lxsession/LXDE-pi/autostart"
if [ -d "${USER_HOME}/.config/lxsession/LXDE-pi" ] || command -v lxsession >/dev/null 2>&1; then
  run_as_user mkdir -p "$(dirname "${LXDE_AUTOSTART}")"
  sudo touch "${LXDE_AUTOSTART}"
  for line in "@xset s off" "@xset -dpms" "@xset s noblank"; do
    sudo grep -qF "${line}" "${LXDE_AUTOSTART}" || echo "${line}" | sudo tee -a "${LXDE_AUTOSTART}" >/dev/null
  done
  sudo chown -R "${ZEE_USER}:${ZEE_USER}" "${USER_HOME}/.config/lxsession"
  ok "LXDE autostart ajustado (sem blanking)"
fi

# 5) Login automático no desktop (necessário para o kiosk abrir sozinho)
if command -v raspi-config >/dev/null 2>&1; then
  if sudo raspi-config nonint do_boot_behaviour B4 >/dev/null 2>&1; then
    ok "boot configurado para desktop com login automático"
  else
    warn "não foi possível ajustar o autologin — use: sudo raspi-config > System Options > Boot / Auto Login"
  fi
else
  warn "raspi-config indisponível: garanta manualmente o login automático no desktop"
fi

echo "==> Kiosk configurado. Reinicie para validar: sudo reboot"
