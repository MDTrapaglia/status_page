#!/bin/bash
set -e

cd "$(dirname "$0")/.."

PID_FILE=".backend.pid"
VENV_PATH="./venv"
HOST="127.0.0.1"
PORT="3010"
WORKERS="${WORKERS:-3}"
TIMEOUT="${TIMEOUT:-120}"

# Kill previous process if exists
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping previous backend process (PID: $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Kill any lingering Flask dev servers
pkill -f "flask run" 2>/dev/null || true
pkill -f "venv/bin/flask" 2>/dev/null || true
sleep 1

# Activate virtual environment
if [[ ! -d "$VENV_PATH" ]]; then
  echo "Virtual environment not found at $VENV_PATH" >&2
  exit 1
fi

source "$VENV_PATH/bin/activate"

GUNICORN_BIN="$VENV_PATH/bin/gunicorn"
if [[ ! -x "$GUNICORN_BIN" ]]; then
  echo "Gunicorn is required but was not found at $GUNICORN_BIN. Run 'pip install -r requirements.txt'." >&2
  exit 1
fi

echo "Compiling app.py..."
python -m py_compile app.py

export FLASK_APP=app
export FLASK_ENV=production
export FLASK_DEBUG=0

echo "Starting Gunicorn (production) on ${HOST}:${PORT} with ${WORKERS} workers..."
"$GUNICORN_BIN" \
  --pid "$PID_FILE" \
  --bind "${HOST}:${PORT}" \
  --workers "$WORKERS" \
  --timeout "$TIMEOUT" \
  --access-logfile - \
  --error-logfile - \
  app:app >/tmp/status_page_gunicorn.log 2>&1 &

sleep 1

if [[ ! -f "$PID_FILE" ]] || ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Failed to start Gunicorn; see /tmp/status_page_gunicorn.log for details." >&2
  exit 1
fi

echo "Backend started in production mode (PID: $(cat "$PID_FILE"))"
echo "URL: http://$HOST:$PORT"
