#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON311="${PYTHON311:-python3.11}"
command -v "$PYTHON311" >/dev/null
command -v clang++ >/dev/null
command -v git >/dev/null
command -v curl >/dev/null
mkdir -p vendor research
EXPECTED=71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33
if [ ! -d vendor/doomfly ]; then
  git clone https://github.com/nftechie/doomfly.git vendor/doomfly
  git -C vendor/doomfly checkout --detach "$EXPECTED"
fi
if [ "$(git -C vendor/doomfly rev-parse HEAD)" != "$EXPECTED" ]; then
  echo 'Upstream version mismatch; preserve existing checkout and review before updating.' >&2
  exit 1
fi
"$PYTHON311" -m venv .venv-neural
.venv-neural/bin/python -m pip install -r requirements-neural.lock.txt --build-constraint vendor/doomfly/neural-build-constraints.txt
.venv-neural/bin/python scripts/download_connectome.py
(
  cd vendor/doomfly
  ../../.venv-neural/bin/python -m doom.build_kernel
  ../../.venv-neural/bin/python -m doom.connectome malecns_v1
  ../../.venv-neural/bin/python -m doom.prepare
  ../../.venv-neural/bin/python -m doom.audit_data
  ../../.venv-neural/bin/python -m pytest tests/test_connectome.py tests/test_doom_reference.py -q
)
.venv-neural/bin/python scripts/probe_connectome.py
.venv-neural/bin/python scripts/validate_neural.py
.venv-neural/bin/python -m unittest discover -s tests -v
