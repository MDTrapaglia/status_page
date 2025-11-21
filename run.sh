#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/venv"

if [[ ! -d "$VENV_PATH" ]]; then
  echo "No se encontró el entorno virtual en $VENV_PATH" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_PATH/bin/activate"

export FLASK_APP=app
flask run --reload --no-debugger
