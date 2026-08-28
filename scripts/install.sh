#!/usr/bin/env bash
# =============================================================================
# Zee Assistant — instalador para Raspberry Pi OS (64 bits)
#
# Uso:   ./scripts/install.sh [--no-model] [--no-kiosk] [--no-apt]
#
# O script é idempotente: pode ser executado novamente sem quebrar nada.
# Nenhuma operação destrutiva é feita sem aviso.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ZEE_USER="${SUDO_USER:-$(id -un)}"
ZEE_UID="$(id -u "${ZEE_USER}")"
VENV="${ZEE_DIR}/venv"

SKIP_MODEL=0
SKIP_KIOSK=0
SKIP_APT=0
for arg in "$@"; do
  case "${arg}" in
    --no-model) SKIP_MODEL=1 ;;
    --no-kiosk) SKIP_KIOSK=1 ;;
    --no-apt)   SKIP_APT=1 ;;
    -h|--help)  sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Argumento desconhecido: ${arg}"; exit 2 ;;
  esac
done

BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
step()  { echo -e "\n${BOLD}==> $*${RESET}"; }
ok()    { echo -e "  ${GREEN}✔${RESET} $*"; }
warn()  { echo -e "  ${YELLOW}!${RESET} $*"; }
fail()  { echo -e "  ${RED}✘${RESET} $*"; }
die()   { fail "$*"; exit 1; }

echo -e "${BOLD}"
echo "  🐝  Zee Assistant — instalação"
echo -e "${RESET}"
echo "  Diretório : ${ZEE_DIR}"
echo "  Usuário   : ${ZEE_USER} (uid ${ZEE_UID})"

[ "${ZEE_USER}" = "root" ] && warn "instalando como root: prefira executar como usuário comum (ex.: pi)"

# -----------------------------------------------------------------------------
step "1/12 Verificando o sistema"
ARCH="$(uname -m)"
echo "  arquitetura: ${ARCH}"
case "${ARCH}" in
  aarch64|arm64) ok "Raspberry Pi OS 64 bits detectado" ;;
  armv7l|armv6l) warn "sistema 32 bits: os wheels do vosk podem não existir para esta arquitetura" ;;
  x86_64)        warn "x86_64 (ambiente de desenvolvimento) — a instalação continua" ;;
  *)             warn "arquitetura não testada: ${ARCH}" ;;
esac
[ -f /etc/rpi-issue ] && ok "Raspberry Pi OS confirmado" || warn "não parece um Raspberry Pi OS"
python3 --version || die "python3 não encontrado"

if ! sudo -n true 2>/dev/null; then
  echo "  (a instalação vai pedir sua senha de sudo)"
fi

# -----------------------------------------------------------------------------
if [ "${SKIP_APT}" -eq 0 ]; then
  step "2/12 Instalando dependências do sistema (apt)"
  sudo apt-get update -qq
  PACKAGES=(
    python3 python3-venv python3-pip python3-dev
    libportaudio2 portaudio19-dev libatlas-base-dev
    alsa-utils mpg123
    unzip wget curl git cmake build-essential ffmpeg
    network-manager
  )
  sudo apt-get install -y "${PACKAGES[@]}"
  ok "pacotes base instalados"

  step "3/12 Chromium"
  if command -v chromium-browser >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
    ok "Chromium já instalado"
  else
    sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium \
      || warn "não foi possível instalar o Chromium automaticamente"
  fi

  step "4/12 iptables (fallback do captive portal)"
  command -v iptables >/dev/null 2>&1 || sudo apt-get install -y iptables || warn "iptables indisponível"
  ok "verificado"
else
  step "2-4/12 apt ignorado (--no-apt)"
fi

# -----------------------------------------------------------------------------
step "5/12 Ambiente virtual Python"
if [ ! -d "${VENV}" ]; then
  # --copies facilita o setcap opcional no interpretador (bind na porta 80)
  python3 -m venv --copies "${VENV}"
  ok "virtualenv criado em ${VENV}"
else
  ok "virtualenv já existe"
fi
"${VENV}/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
ok "pip atualizado"

step "6/12 Dependências Python"
"${VENV}/bin/pip" install -r "${ZEE_DIR}/requirements.txt"
ok "requirements.txt instalado"

# -----------------------------------------------------------------------------
step "7/12 Modelo Vosk PT-BR"
if [ "${SKIP_MODEL}" -eq 1 ]; then
  warn "download do modelo ignorado (--no-model)"
elif [ -f "${ZEE_DIR}/models/vosk/pt-br/final.mdl" ] || [ -f "${ZEE_DIR}/models/vosk/pt-br/am/final.mdl" ]; then
  ok "modelo já instalado em models/vosk/pt-br"
else
  bash "${SCRIPT_DIR}/download_vosk_model.sh" || warn "falha ao baixar o modelo — a voz ficará desativada até você instalá-lo"
fi

if [ "${SKIP_MODEL}" -eq 0 ]; then
  step "7b/12 whisper.cpp para comandos em português"
  bash "${SCRIPT_DIR}/install_whisper.sh" \
    || warn "whisper.cpp indisponível — os comandos continuarão usando Vosk"
fi

if [ "${SKIP_MODEL}" -eq 0 ]; then
  step "7c/12 Piper TTS em português do Brasil"
  bash "${SCRIPT_DIR}/install_piper.sh" \
    || warn "Piper indisponível — as respostas continuarão somente na tela"
fi

# -----------------------------------------------------------------------------
step "8/12 Permissões e grupos"
for grp in audio netdev video; do
  if getent group "${grp}" >/dev/null; then
    sudo usermod -aG "${grp}" "${ZEE_USER}" && ok "usuário ${ZEE_USER} adicionado ao grupo ${grp}"
  fi
done
mkdir -p "${ZEE_DIR}/logs"
touch "${ZEE_DIR}/logs/zee.log"
sudo chown -R "${ZEE_USER}:${ZEE_USER}" "${ZEE_DIR}/logs"
ok "diretório de logs pronto"

NMCLI_BIN="$(command -v nmcli || echo /usr/bin/nmcli)"
IPTABLES_BIN="$(command -v iptables || echo /usr/sbin/iptables)"
RFKILL_BIN="$(command -v rfkill || echo /usr/sbin/rfkill)"
SUDOERS_TMP="$(mktemp)"
sed -e "s|__ZEE_USER__|${ZEE_USER}|g" \
    -e "s|__NMCLI__|${NMCLI_BIN}|g" \
    -e "s|__IPTABLES__|${IPTABLES_BIN}|g" \
    -e "s|__RFKILL__|${RFKILL_BIN}|g" \
    "${ZEE_DIR}/config/system/zee-assistant.sudoers" > "${SUDOERS_TMP}"
if sudo visudo -cf "${SUDOERS_TMP}" >/dev/null; then
  sudo install -m 0440 -o root -g root "${SUDOERS_TMP}" /etc/sudoers.d/zee-assistant
  ok "sudoers instalado (nmcli/iptables/rfkill sem senha)"
else
  fail "arquivo sudoers inválido — configuração de Wi-Fi exigirá senha"
fi
rm -f "${SUDOERS_TMP}"

# -----------------------------------------------------------------------------
step "9/12 NetworkManager e captive portal"
if systemctl list-unit-files | grep -q '^NetworkManager.service'; then
  sudo systemctl enable --now NetworkManager >/dev/null 2>&1 || true
  ok "NetworkManager ativo"
  sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
  sudo install -m 0644 "${ZEE_DIR}/config/system/zee-captive.dnsmasq.conf" \
       /etc/NetworkManager/dnsmasq-shared.d/zee-captive.conf
  ok "DNS wildcard do captive portal instalado"
else
  warn "NetworkManager não encontrado: a configuração de Wi-Fi por QR Code não funcionará"
fi

# Permite ao Python abrir a porta 80 sem root (captive portal).
if command -v setcap >/dev/null 2>&1 && [ -f "${VENV}/bin/python3" ]; then
  if sudo setcap 'cap_net_bind_service=+ep' "$(readlink -f "${VENV}/bin/python3")" 2>/dev/null; then
    ok "python do venv autorizado a usar a porta 80"
  else
    warn "setcap falhou — o portal usará a porta 8080 com redirecionamento iptables"
  fi
fi

# -----------------------------------------------------------------------------
step "10/12 Serviço systemd"
SERVICE_TMP="$(mktemp)"
sed -e "s|__ZEE_DIR__|${ZEE_DIR}|g" \
    -e "s|__ZEE_USER__|${ZEE_USER}|g" \
    -e "s|__ZEE_UID__|${ZEE_UID}|g" \
    "${ZEE_DIR}/systemd/zee-assistant.service" > "${SERVICE_TMP}"
sudo install -m 0644 -o root -g root "${SERVICE_TMP}" /etc/systemd/system/zee-assistant.service
rm -f "${SERVICE_TMP}"
sudo systemctl daemon-reload
sudo systemctl enable zee-assistant.service >/dev/null
ok "zee-assistant.service instalado e habilitado no boot"

# -----------------------------------------------------------------------------
step "11/12 Modo kiosk (Chromium)"
if [ "${SKIP_KIOSK}" -eq 1 ]; then
  warn "configuração do kiosk ignorada (--no-kiosk)"
else
  bash "${SCRIPT_DIR}/configure_kiosk.sh" || warn "não foi possível configurar o kiosk automaticamente"
fi

# -----------------------------------------------------------------------------
step "12/12 Iniciando o serviço"
sudo systemctl restart zee-assistant.service
sleep 3
if systemctl is-active --quiet zee-assistant.service; then
  ok "zee-assistant está rodando"
else
  fail "o serviço não subiu — veja: journalctl -u zee-assistant -n 50"
fi

PORT="$(python3 - "$ZEE_DIR/config/config.json" <<'PY' 2>/dev/null || echo 5000
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        print(json.load(fh).get("app", {}).get("port", 5000))
except Exception:
    print(5000)
PY
)"

cat <<EOF

$(echo -e "${GREEN}${BOLD}") Instalação concluída! $(echo -e "${RESET}")

  Interface     : http://127.0.0.1:${PORT}
  Serviço       : sudo systemctl status zee-assistant
  Logs          : tail -f ${ZEE_DIR}/logs/zee.log
                  journalctl -u zee-assistant -f
  Reiniciar     : sudo systemctl restart zee-assistant

  Próximos passos:
    1. Confira a animação em static/assets/images/zee-circulo.mp4
    2. Coloque o áudio em static/assets/audio/oi_estou_ouvindo.mp3
    3. Edite os conteúdos em data/recursos.json
    4. Reinicie o Raspberry Pi para validar o boot automático:  sudo reboot

  Se este Raspberry Pi ainda não tem Wi-Fi salvo, após o boot a tela mostrará
  o QR Code da rede Zee-Setup-XXXX para configuração pelo celular.

EOF
