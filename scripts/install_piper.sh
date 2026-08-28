#!/usr/bin/env bash
# Instala o Piper TTS e a voz brasileira Faber (qualidade média).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV="${ZEE_DIR}/venv"
MODEL_DIR="${ZEE_DIR}/models/piper"
MODEL_PATH="${MODEL_DIR}/pt_BR-faber-medium.onnx"

if [ ! -x "${VENV}/bin/python" ]; then
  echo "Ambiente virtual não encontrado em ${VENV}. Execute scripts/install.sh primeiro." >&2
  exit 1
fi

"${VENV}/bin/pip" install 'piper-tts>=1.3,<2'
mkdir -p "${MODEL_DIR}"

if [ ! -f "${MODEL_PATH}" ] || [ ! -f "${MODEL_PATH}.json" ]; then
  "${VENV}/bin/python" -m piper.download_voices \
    --data-dir "${MODEL_DIR}" pt_BR-faber-medium
fi

echo "Piper instalado com a voz: ${MODEL_PATH}"
