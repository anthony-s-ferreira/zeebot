#!/usr/bin/env bash
# Instala o whisper.cpp e o modelo base multilíngue quantizado para comandos.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZEE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WHISPER_DIR="${ZEE_DIR}/tools/whisper.cpp"
BINARY="${WHISPER_DIR}/build/bin/whisper-cli"
SERVER_BINARY="${WHISPER_DIR}/build/bin/whisper-server"
MODEL_DIR="${ZEE_DIR}/models/whisper"
MODEL_PATH="${MODEL_DIR}/ggml-base-q5_1.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base-q5_1.bin?download=true"

for command in git cmake curl ffmpeg; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "${command} não encontrado. Instale git, cmake, build-essential, curl e ffmpeg." >&2
    exit 1
  }
done

if [ ! -d "${WHISPER_DIR}/.git" ]; then
  mkdir -p "$(dirname "${WHISPER_DIR}")"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "${WHISPER_DIR}"
fi

cmake -S "${WHISPER_DIR}" -B "${WHISPER_DIR}/build" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "${WHISPER_DIR}/build" --config Release -j "$(nproc)" \
  --target whisper-cli whisper-server

mkdir -p "${MODEL_DIR}"
if [ ! -f "${MODEL_PATH}" ]; then
  echo "Baixando modelo Whisper base multilíngue quantizado (~60 MB)..."
  curl -L --fail --progress-bar "${MODEL_URL}" -o "${MODEL_PATH}.part"
  mv "${MODEL_PATH}.part" "${MODEL_PATH}"
fi

echo "whisper.cpp instalado: ${BINARY}"
echo "whisper-server instalado: ${SERVER_BINARY}"
echo "modelo instalado: ${MODEL_PATH}"
