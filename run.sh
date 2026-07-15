#!/usr/bin/env bash
# run.sh — Quick-start script for Athena Assistant (macOS / Linux)
# Usage: bash run.sh [--port PORT]
# Environment: PORT env var also respected (default 8000)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
PORT="${PORT:-8000}"

# Parse --port argument
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    *) echo "Unknown argument: $1"; exit 1;;
  esac
done

# Require Python 3
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Please install Python 3.11 or later." >&2
  exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Install / update dependencies
echo "Installing dependencies..."
pip install --quiet -r requirements.txt

# Ensure runtime directories exist
mkdir -p logs audit data/carddav_staged

# Copy .env.example if .env is missing
if [ ! -f ".env" ]; then
  echo "Notice: .env not found — copying from .env.example. Edit it before running in production."
  cp .env.example .env
fi

echo "Starting Athena Assistant on http://0.0.0.0:${PORT} ..."
uvicorn main:app --reload --host 0.0.0.0 --port "$PORT"
