#!/usr/bin/env bash
# Run GAMSPy INRE scenarios outside the PyPSA pixi environment.
# GAMSPy is installed via pip (not in pixi.toml); pixi shell uses a Python without gamspy.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

find_python() {
  if [[ -n "${GAMSPY_PYTHON:-}" ]] && "$GAMSPY_PYTHON" -c "import gamspy" 2>/dev/null; then
    echo "$GAMSPY_PYTHON"
    return 0
  fi
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import gamspy" 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

if [[ -n "${VIRTUAL_ENV:-}" ]] && [[ "${VIRTUAL_ENV}" == *"/.pixi/"* ]]; then
  echo "ERROR: You are inside the PyPSA pixi shell. GAMSPy is not installed there." >&2
  echo "Run: exit   (leave pixi shell), then:" >&2
  echo "  cd gamspy-de && ./run_scenarios.sh --scenario all" >&2
  exit 1
fi

PYTHON="$(find_python)" || {
  echo "ERROR: No Python with 'gamspy' found." >&2
  echo "Install once (outside pixi shell):" >&2
  echo "  pip install -r gamspy-de/requirements.txt" >&2
  echo "  gamspy install solver highs" >&2
  exit 1
}

echo "Using Python: $PYTHON ($("$PYTHON" -c 'import gamspy; print(gamspy.__version__)'))"
exec "$PYTHON" src/run.py "$@"
