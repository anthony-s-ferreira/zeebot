#!/usr/bin/env bash
# Baixa e instala o modelo Vosk PT-BR em models/vosk/pt-br
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODEL_DIR="${ZEE_DIR}/models/vosk"
TARGET="${MODEL_DIR}/pt-br"

MODEL_NAME="${ZEE_VOSK_MODEL:-vosk-model-small-pt-0.3}"
MODEL_URL="${ZEE_VOSK_URL:-https://alphacephei.com/vosk/models/${MODEL_NAME}.zip}"

echo "==> Modelo: ${MODEL_NAME}"
echo "    Destino: ${TARGET}"

# Modelos "small" têm final.mdl na raiz; os grandes, em am/final.mdl.
model_ok() { [ -e "$1/final.mdl" ] || [ -e "$1/am/final.mdl" ]; }

if [ -d "${TARGET}" ] && model_ok "${TARGET}"; then
  echo "    Modelo já instalado. Nada a fazer."
  echo "    (use --force para reinstalar)"
  [ "${1:-}" = "--force" ] || exit 0
  echo "    Removendo instalação anterior..."
  rm -rf "${TARGET}"
fi

mkdir -p "${MODEL_DIR}"
TMP_ZIP="${MODEL_DIR}/${MODEL_NAME}.zip"

echo "==> Baixando (pode levar alguns minutos)..."
if command -v wget >/dev/null 2>&1; then
  wget --show-progress -q -O "${TMP_ZIP}" "${MODEL_URL}"
elif command -v curl >/dev/null 2>&1; then
  curl -L --progress-bar -o "${TMP_ZIP}" "${MODEL_URL}"
else
  echo "ERRO: instale wget ou curl" >&2
  exit 1
fi

echo "==> Extraindo..."
unzip -q -o "${TMP_ZIP}" -d "${MODEL_DIR}"
rm -f "${TMP_ZIP}"

if [ -d "${MODEL_DIR}/${MODEL_NAME}" ]; then
  rm -rf "${TARGET}"
  mv "${MODEL_DIR}/${MODEL_NAME}" "${TARGET}"
fi

if model_ok "${TARGET}"; then
  echo "==> Modelo instalado com sucesso em ${TARGET}"
  du -sh "${TARGET}"
else
  echo "ERRO: estrutura inesperada. Confira o conteúdo de ${MODEL_DIR}" >&2
  exit 1
fi
