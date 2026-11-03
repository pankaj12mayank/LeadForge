#!/usr/bin/env bash
# Idempotent VPS setup for LeadForge (Ubuntu). No Docker.
set -euo pipefail

DOMAIN="${DOMAIN:-leadforge.example.com}"
APP_DIR="/opt/leadforge"
PYTHON="${PYTHON:-python3}"

echo "[setup] installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y postgresql postgresql-contrib python3-venv python3-pip caddy curl git

echo "[setup] creating database and user..."
DB_NAME="${DB_NAME:-leadforge}"
DB_USER="${DB_USER:-leadforge}"
DB_PASSWORD="$(openssl rand -hex 24)"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASSWORD';"
sudo -u postgres createdb -O "$DB_USER" "$DB_NAME" 2>/dev/null || true

echo "[setup] creating app directory and venv..."
mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[setup] writing .env..."
SECRET_KEY="$(openssl rand -hex 32)"
cat > "$APP_DIR/.env" <<EOF
APP_NAME=LeadForge
APP_ENV=prod
SECRET_KEY=$SECRET_KEY
BASE_URL=https://$DOMAIN
PORT=8000
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg2://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
DB_POOL_SIZE=5
LLM_PROVIDER=none
LLM_TIMEOUT=60
LLM_MAX_RETRIES=3
TRIAL_CREDITS=10
TRIAL_DAYS=7
RATE_LIMIT_JOBS_PER_HOUR=20
KEY_MODE=platform
EOF
echo "DATABASE_USER=$DB_USER" >> "$APP_DIR/.env.db"
echo "DATABASE_PASSWORD=$DB_PASSWORD" >> "$APP_DIR/.env.db"
echo "DATABASE_NAME=$DB_NAME" >> "$APP_DIR/.env.db"
chmod 600 "$APP_DIR/.env" "$APP_DIR/.env.db"

echo "[setup] migrations + seed..."
cd "$APP_DIR"
"$APP_DIR/venv/bin/alembic" upgrade head
"$APP_DIR/venv/bin/python" -m scripts.seed

echo "[setup] systemd units..."
cat > /etc/systemd/system/leadforge-web.service <<UNIT
[Unit]
Description=LeadForge web
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
User=root

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/leadforge-worker.service <<UNIT
[Unit]
Description=LeadForge worker
After=network.target postgresql.service leadforge-web.service

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python -m app.worker
Restart=always
User=root

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now leadforge-web leadforge-worker

echo "[setup] Caddy reverse proxy + HTTPS..."
cat > /etc/caddy/Caddyfile <<CF
$DOMAIN {
    reverse_proxy localhost:8000
}
CF
systemctl enable --now caddy

echo "[setup] daily pg_dump backup (7-day retention)..."
cat > /etc/cron.d/leadforge-backup <<CRON
0 2 * * * root pg_dump -U $DB_USER -d $DB_NAME | gzip > /var/backups/leadforge/\$(date +\%F).sql.gz && find /var/backups/leadforge -mtime +7 -delete
CRON
mkdir -p /var/backups/leadforge
chmod 600 /etc/cron.d/leadforge-backup
service cron reload 2>/dev/null || true

echo "[setup] done. Web: https://$DOMAIN  Worker running via systemd"
