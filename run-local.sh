#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
exec docker compose -f docker-compose.neural.yml -f docker-compose.local.yml run --rm flycoder-neural "$@"
