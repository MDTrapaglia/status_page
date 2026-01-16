#!/bin/bash
set -e

# Stop backend development server
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Stopping backend..."
"$SCRIPT_DIR/backend_stop.sh"

echo "All services stopped"
