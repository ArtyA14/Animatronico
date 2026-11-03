#!/usr/bin/env bash
# Arranca Ollama con la configuración pensada para 6 GB de VRAM.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLLAMA_BIN="${OLLAMA_BIN:-$HOME/.local/opt/ollama/bin/ollama}"

export OLLAMA_MODELS="${OLLAMA_MODELS:-$ROOT/models/ollama}"
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:--1}"      # no descargar el modelo de VRAM
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"   # una sola conversación a la vez
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"

mkdir -p "$OLLAMA_MODELS"
exec "$OLLAMA_BIN" serve
