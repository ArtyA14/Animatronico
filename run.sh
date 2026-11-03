#!/usr/bin/env bash
# Lanzador corto: ./run.sh --texto
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python main.py "$@"
