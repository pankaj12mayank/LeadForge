# Deployment

## Render / Railway
- Push to git; Render builds from `requirements.txt`.
- `Procfile`: web = `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; worker = `python -m app.worker`.
- `render.yaml`: two services + managed `leadforge-db` Postgres.
- Release command: `alembic upgrade head && python -m scripts.seed`.
- Set env vars in Render dashboard (see `.env.example`).

## VPS (Ubuntu)
```bash
sudo ./scripts/setup_vps.sh   # DOMAIN=your.domain
# creates DB, venv, installs deps, runs alembic + seed, systemd units, Caddy HTTPS, backups
./scripts/update.sh           # git pull, deps, migrate, seed, restart
./scripts/rollback.sh         # previous commit, migrate, restart
```
Services: `leadforge-web`, `leadforge-worker`. Web behind Caddy at `https://$DOMAIN`.

## Local dev
```bash
python scripts/dev_db.py            # embedded Postgres on 54320
cp .env.example .env                # set DATABASE_URL to dev_db URL
python -m scripts.seed
uvicorn app.main:app --reload       # terminal 1
python -m app.worker                # terminal 2
```
