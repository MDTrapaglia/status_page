#!/bin/bash
set -e

# Start backend and frontend development servers
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Stopping existing services (if any)..."
"$SCRIPT_DIR/stop_all.sh" || true

echo "Starting backend..."
"$SCRIPT_DIR/backend_start.sh"

echo "All services started"
