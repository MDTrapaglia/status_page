#!/bin/bash
cd "$(dirname "$0")/.."

PID_FILE=".backend.pid"

# Stop Flask processes by PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping backend process (PID: $PID)..."
        kill "$PID"
        rm -f "$PID_FILE"
        echo "Backend process stopped"
    else
        echo "Backend process no longer exists"
        rm -f "$PID_FILE"
    fi
else
    echo "No PID file found"
fi

# Kill any lingering Flask/Gunicorn processes
echo "Stopping any remaining Flask/Gunicorn processes..."
pkill -f "flask run" 2>/dev/null && echo "Flask processes stopped" || echo "No Flask processes found"
pkill -f "venv/bin/flask" 2>/dev/null || true
pkill -f "gunicorn .*app:app" 2>/dev/null && echo "Gunicorn processes stopped" || echo "No Gunicorn processes found"

# Kill processes on port 3010
if command -v fuser >/dev/null 2>&1; then
    fuser -k 3010/tcp 2>/dev/null || true
fi

echo "Backend stopped completely"
