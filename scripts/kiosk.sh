#!/usr/bin/env bash
# Inicia o Chromium em modo kiosk apontando para o Zee Assistant.
# Chamado pelo autostart da sessão gráfica (ver configure_kiosk.sh).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PORT="$(python3 - "${ZEE_DIR}/config/config.json" <<'PY' 2>/dev/null || echo 5000
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        print(json.load(fh).get("app", {}).get("port", 5000))
except Exception:
    print(5000)
PY
)"
URL="http://127.0.0.1:${PORT}"
PROFILE="${HOME}/.config/zee-kiosk"

log() { echo "[zee-kiosk] $*"; }

# ---------------------------------------------------------- desliga o blanking
if [ "${XDG_SESSION_TYPE:-}" = "x11" ] && command -v xset >/dev/null 2>&1; then
  xset s off || true
  xset -dpms || true
  xset s noblank || true
  command -v unclutter >/dev/null 2>&1 && (unclutter -idle 0.5 -root &) || true
fi
command -v wlr-randr >/dev/null 2>&1 && wlr-randr --output "$(wlr-randr | head -1 | cut -d' ' -f1)" --on >/dev/null 2>&1 || true

# ------------------------------------------------------- espera o backend subir
log "aguardando ${URL}/healthz ..."
for _ in $(seq 1 90); do
  if curl -fsS --max-time 2 "${URL}/healthz" >/dev/null 2>&1; then
    log "backend pronto"
    break
  fi
  sleep 1
done

# ------------------------------------------------------------ escolhe o binário
CHROMIUM=""
for candidate in chromium-browser chromium google-chrome-stable; do
  if command -v "${candidate}" >/dev/null 2>&1; then CHROMIUM="${candidate}"; break; fi
done
[ -z "${CHROMIUM}" ] && { log "ERRO: Chromium não encontrado"; exit 1; }
log "usando ${CHROMIUM}"

CHROMIUM_ARGS=(
  --kiosk
  --app="${URL}"
  --user-data-dir="${PROFILE}"
  --start-fullscreen
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --disable-features=Translate,TranslateUI,AutofillServerCommunication
  --disable-translate
  --disable-pinch
  --overscroll-history-navigation=0
  --autoplay-policy=no-user-gesture-required
  --disable-background-networking
  --disable-component-extensions-with-background-pages
  --disable-default-apps
  --disable-domain-reliability
  --disable-extensions
  --disable-sync
  --disable-component-update
  --password-store=basic
  --no-first-run
  --enable-features=OverlayScrollbar
)

# Evita a camada XWayland no Raspberry Pi OS Bookworm/labwc. Em sessões X11,
# deixa o Chromium escolher o backend compatível para não causar tela preta.
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
  CHROMIUM_ARGS+=(--ozone-platform=wayland)
  log "renderização nativa Wayland ativada"
fi

# Evita o balão "O Chromium não foi encerrado corretamente".
if [ -f "${PROFILE}/Default/Preferences" ]; then
  sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' \
      "${PROFILE}/Default/Preferences" 2>/dev/null || true
fi

exec "${CHROMIUM}" "${CHROMIUM_ARGS[@]}"
