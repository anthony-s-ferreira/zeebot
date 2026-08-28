#!/usr/bin/env bash
# Diagnóstico rápido de áudio no Raspberry Pi (microfone + alto-falante).
set -uo pipefail

BOLD="\033[1m"; RESET="\033[0m"; GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"
title() { echo -e "\n${BOLD}==> $*${RESET}"; }
ok()    { echo -e "  ${GREEN}✔${RESET} $*"; }
bad()   { echo -e "  ${RED}✘${RESET} $*"; }
warn()  { echo -e "  ${YELLOW}!${RESET} $*"; }

title "Dispositivos de captura (arecord -l)"
if arecord -l 2>/dev/null | grep -q "card"; then
  arecord -l
  ok "microfone detectado pelo ALSA"
else
  bad "nenhum microfone detectado"
  echo "     • USB: desconecte e reconecte, depois rode 'dmesg | tail'"
  echo "     • I2S: confirme o dtoverlay em /boot/firmware/config.txt"
fi

title "Dispositivos de reprodução (aplay -l)"
aplay -l 2>/dev/null || bad "nenhuma saída de áudio encontrada"

title "Volumes (amixer)"
amixer 2>/dev/null | grep -A3 -E "Simple mixer control '(Master|PCM|Mic|Capture)'" | head -30 \
  || warn "amixer não retornou controles"

title "Teste de gravação (3 segundos)"
TMP_WAV="$(mktemp --suffix=.wav)"
if arecord -f S16_LE -r 16000 -c 1 -d 3 "${TMP_WAV}" 2>/dev/null; then
  SIZE="$(stat -c%s "${TMP_WAV}" 2>/dev/null || echo 0)"
  if [ "${SIZE}" -gt 10000 ]; then
    ok "gravado ${SIZE} bytes em ${TMP_WAV}"
    title "Reproduzindo o que foi gravado"
    aplay "${TMP_WAV}" 2>/dev/null && ok "reprodução concluída" || bad "falha ao reproduzir"
  else
    bad "arquivo muito pequeno (${SIZE} bytes) — microfone mudo?"
  fi
else
  bad "arecord falhou — verifique se outro processo está usando o microfone"
  echo "     sudo systemctl stop zee-assistant   # libera o microfone e tente de novo"
fi
rm -f "${TMP_WAV}"

title "Players de MP3 disponíveis"
for player in mpg123 mpv ffplay cvlc; do
  command -v "${player}" >/dev/null 2>&1 && ok "${player}" || warn "${player} ausente"
done

title "Áudio de boas-vindas"
WELCOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/static/assets/audio/oi_estou_ouvindo.mp3"
if [ -f "${WELCOME}" ]; then
  ok "encontrado: ${WELCOME}"
  command -v mpg123 >/dev/null 2>&1 && mpg123 -q "${WELCOME}" && ok "reproduzido"
else
  warn "ausente: ${WELCOME} (o sistema continua funcionando, sem a saudação)"
fi

echo
