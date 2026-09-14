#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$ROOT/.venv-neural/bin/python" ]; then
  echo 'Run bash scripts/setup_neural.sh first.' >&2
  exit 2
fi
exec "$ROOT/.venv-neural/bin/python" "$ROOT/scripts/run_neural.py" "$@"
