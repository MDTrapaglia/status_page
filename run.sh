#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/venv"
SELF_PID="$$"
SELF_PPID="${PPID:-}"

kill_running() {
  local pids=""
  # Flask dev server (main + reloader)
  pids+=" $(pgrep -f "venv/bin/flask run" || true)"
  pids+=" $(pgrep -f "python .*flask run" || true)"
  # Any lingering run.sh shells
  pids+=" $(pgrep -f "bash ./run.sh" || true)"

  # Processes holding port 80, if fuser is available
  if command -v fuser >/dev/null 2>&1; then
    pids+=" $(fuser 80/tcp 2>/dev/null || true)"
  fi

  # Deduplicate and remove empty tokens
  pids=$(echo "$pids" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u || true)
  # Exclude this script/process tree
  pids=$(echo "$pids" | grep -Ev "^(${SELF_PID}|${SELF_PPID})$" || true)

  if [[ -n "$pids" ]]; then
    echo "Deteniendo procesos previos: $pids" >&2
    # First try graceful, then force
    kill $pids 2>/dev/null || true
    sleep 1
    kill -9 $pids 2>/dev/null || true
  fi
}

if [[ ! -d "$VENV_PATH" ]]; then
  echo "No se encontró el entorno virtual en $VENV_PATH" >&2
  exit 1
fi

kill_running

# shellcheck disable=SC1091
source "$VENV_PATH/bin/activate"

echo "Compilando app.py..."
python -m py_compile "$SCRIPT_DIR/app.py"

export FLASK_APP=app
echo "Iniciando servidor Flask en puerto 80..."
flask run --reload --no-debugger --host 0.0.0.0 --port 80
