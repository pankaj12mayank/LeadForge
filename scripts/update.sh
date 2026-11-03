#!/usr/bin/env bash
# Idempotent update: git pull, install deps, migrate, seed, restart services.
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/leadforge}"
cd "$APP_DIR"
git pull --ff-only
"$APP_DIR/venv/bin/pip" install -r requirements.txt
"$APP_DIR/venv/bin/alembic" upgrade head
"$APP_DIR/venv/bin/python" -m scripts.seed
systemctl restart leadforge-web leadforge-worker
echo "updated and restarted"
