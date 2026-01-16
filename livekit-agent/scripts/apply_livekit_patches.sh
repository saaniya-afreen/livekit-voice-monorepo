#!/usr/bin/env bash
set -euo pipefail

# Apply local LiveKit patch files from ./patches into the currently active python environment.
# Usage:
#   source venv/bin/activate
#   ./scripts/apply_livekit_patches.sh

PYTHON_BIN="${PYTHON_BIN:-python}"

SITE_PACKAGES="$($PYTHON_BIN -c 'import site; print(site.getsitepackages()[0])')"
echo "Using site-packages: ${SITE_PACKAGES}"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/patches"

copy_file() {
  local rel="$1"
  local src="${SRC_DIR}/${rel}"
  local dst="${SITE_PACKAGES}/${rel}"
  if [[ ! -f "${src}" ]]; then
    echo "Missing source: ${src}" >&2
    exit 1
  fi
  mkdir -p "$(dirname "${dst}")"
  cp "${src}" "${dst}"
  echo "Patched: ${dst}"
}

copy_file "livekit/agents/inference/llm.py"
copy_file "livekit/agents/llm/llm.py"

echo "Done. Restart the agent process to pick up changes."

