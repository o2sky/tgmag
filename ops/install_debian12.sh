#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip build-essential libpq-dev postgresql-client

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel "setuptools>=83"
pip install -r requirements.txt

mkdir -p data/sessions data/backups

echo "Install complete."
echo "Next:"
echo "  cp .env.example .env"
echo "  edit .env"
echo "  source .venv/bin/activate && alembic upgrade head"
echo "  python -m app.main"
