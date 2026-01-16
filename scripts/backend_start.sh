#!/bin/bash
cd "$(dirname "$0")/.."

PID_FILE=".backend.pid"
VENV_PATH="./venv"

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

# Kill any lingering Flask processes
pkill -f "flask run" 2>/dev/null || true
pkill -f "venv/bin/flask" 2>/dev/null || true
sleep 1

# Activate virtual environment and start Flask
if [[ ! -d "$VENV_PATH" ]]; then
  echo "Virtual environment not found at $VENV_PATH" >&2
  exit 1
fi

source "$VENV_PATH/bin/activate"

echo "Compiling app.py..."
python -m py_compile app.py

export FLASK_APP=app
echo "Starting Flask server on port 80..."
flask run --reload --no-debugger --host 0.0.0.0 --port 80 &
echo $! > "$PID_FILE"
echo "Backend started (PID: $(cat $PID_FILE))"
echo "URL: http://localhost:80"
