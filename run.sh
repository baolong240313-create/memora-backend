#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || { echo "python3 not found — install Python 3 first."; exit 1; }

echo "Installing dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "Starting Memora... (keep this window open)"
python3 app.py