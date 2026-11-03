#!/usr/bin/env bash
# Rollback to previous commit, re-migrate/seed, restart.
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/leadforge}"
cd "$APP_DIR"
git reset --hard HEAD~1
"$APP_DIR/venv/bin/pip" install -r requirements.txt
"$APP_DIR/venv/bin/alembic" upgrade head
"$APP_DIR/venv/bin/python" -m scripts.seed
systemctl restart leadforge-web leadforge-worker
echo "rolled back and restarted"
