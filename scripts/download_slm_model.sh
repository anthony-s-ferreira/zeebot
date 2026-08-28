#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="$ROOT_DIR/models/slm"
MODEL_PATH="$MODEL_DIR/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
URL="https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf?download=true"

mkdir -p "$MODEL_DIR"
if [[ -f "$MODEL_PATH" ]]; then
  echo "SLM já existe: $MODEL_PATH"
  exit 0
fi

command -v curl >/dev/null || { echo "curl é obrigatório" >&2; exit 1; }
echo "Baixando SLM (~500 MB)..."
curl -L --fail --progress-bar "$URL" -o "$MODEL_PATH"
echo "Modelo salvo em: $MODEL_PATH"
