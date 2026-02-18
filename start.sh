#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d "venv" ]]; then
  python3 -m venv venv
fi

source venv/bin/activate

# Editable installs require setuptools/wheel in the active venv.
if ! python -c "import setuptools, wheel" >/dev/null 2>&1; then
  echo "Bootstrapping packaging tools (setuptools, wheel)..."
  if ! python -m pip install --upgrade setuptools wheel; then
    echo "Failed to install setuptools/wheel."
    echo "Activate the venv and run: python -m pip install --upgrade setuptools wheel"
    exit 1
  fi
fi

if ! python -c "import pydantic_settings, langgraph" >/dev/null 2>&1; then
  echo "Installing missing dependencies into venv..."
  if ! python -m pip install --no-build-isolation -e .; then
    echo "Failed to install dependencies automatically."
    echo "Activate the venv and run: python -m pip install --no-build-isolation -e ."
    exit 1
  fi
fi

exec python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
