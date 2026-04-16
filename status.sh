#!/usr/bin/env bash
set -euo pipefail

# Comprueba si el servidor Flask de status_page está corriendo.

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

collect_pids() {
  local raw=""
  raw+=" $(pgrep -f "venv/bin/flask run" || true)"
  raw+=" $(pgrep -f "python .*flask run" || true)"
  raw+=" $(pgrep -f "bash ./run.sh" || true)"
  if command -v fuser >/dev/null 2>&1; then
    raw+=" $(fuser 80/tcp 2>/dev/null || true)"
  fi

  echo "$raw" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u
}

main() {
  mapfile -t pids < <(collect_pids)
  if [[ ${#pids[@]} -eq 0 ]]; then
    echo "Servidor Flask NO está corriendo."
    exit 1
  fi

  echo "Servidor Flask detectado en PIDs: ${pids[*]}"
  ps -o pid,ppid,cmd -p "${pids[@]}"
}

main "$@"
