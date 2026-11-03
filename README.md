# LeadForge

**Project name:** LeadForge (everywhere). The product and repo are LeadForge; "LeadForge" references have been removed.

## What it is

LeadForge is a multi-tenant lead-sourcing SaaS. A user types one natural-language query, e.g.:

```
India fintech startups whose founders do manual reporting, 20 leads
```

The system creates a job; an AI planner picks sources; sources run in parallel; results are merged, deduplicated, enriched, AI-scored; the user sees leads in a dashboard and can export them.

**Surfaces:** Landing page, User app, Admin panel.  
**Stack:** Python 3.11, FastAPI, PostgreSQL (Alembic), Jinja2 + HTMX + Tailwind (CDN), openpyxl (export only). No Docker, Redis, Celery, Node, or Selenium.

## Quick start (Linux / Windows, no Docker)

```bash
cd LeadForge
python -m venv venv
# Linux:
source venv/bin/activate
# Windows PowerShell:
venv\Scripts\Activate.ps1

pip install -r requirements.txt

# 1. Start embedded Postgres for local dev (prints DATABASE_URL)
python scripts/dev_db.py   # leave this running in a terminal

# 2. Copy env and set DATABASE_URL to the URL printed above
copy .env.example .env      # Windows
# cp .env.example .env      # Linux
# edit .env: DATABASE_URL=postgresql+psycopg2://postgres:@127.0.0.1:54320/postgres

# 3. Seed plans + admin user
python -m scripts.seed

# 4. Run web + worker (two terminals)
uvicorn app.main:app --reload        # http://127.0.0.1:8000
python -m app.worker                 # background job processor
```

Default admin seed (from `.env`): `ADMIN_EMAIL=admin@leadforge.local`, `ADMIN_PASSWORD=AdminPass123!`.

## Admin user

After seeding, sign in at `http://127.0.0.1:8000/auth/login` with:

- Email: `admin@leadforge.local`
- Password: `AdminPass123!` (change `ADMIN_PASSWORD` in `.env` before seeding for production)

The admin can access `/admin` to view users, orgs, jobs, MRR, failure rate; suspend/activate users and orgs; grant credits; change plans; retry/cancel failed jobs; edit plans; view provider health and audit log.

### Admin screenshots

Add screenshots here after you run the app locally. Capture these pages and paste the image files into `docs/screenshots/`, then reference them:

1. **Login page** — `http://127.0.0.1:8000/auth/login`
   ```
   ![Admin login](docs/screenshots/admin-login.png)
   ```
2. **Dashboard** — `http://127.0.0.1:8000/dashboard` (credits, plan, recent jobs)
   ```
   ![Dashboard](docs/screenshots/dashboard.png)
   ```
3. **Jobs page** — `http://127.0.0.1:8000/jobs/<id>` (status polling via HTMX)
   ```
   ![Job status](docs/screenshots/job-status.png)
   ```
4. **Leads table** — `http://127.0.0.1:8000/leads` (filter, sort, bulk status, export)
   ```
   ![Leads table](docs/screenshots/leads-table.png)
   ```
5. **Admin panel** — `http://127.0.0.1:8000/admin` (overview, users/orgs, jobs, plans)
   ```
   ![Admin panel](docs/screenshots/admin-panel.png)
   ```

I cannot generate real screenshots for you; run the app and take the above screenshots, then paste them into `docs/screenshots/` and uncomment the image lines.

## Run commands

- `python -m scripts.seed` — seed/update the 2 plans (Starter, Pro) and admin user.
- `uvicorn app.main:app --reload` — web app (port 8000).
- `python -m app.worker` — background job worker + saved-search scheduler.
- `alembic upgrade head` — run database migrations.
- `python -m pytest -q` — test suite (uses embedded pgserver Postgres).

## Environment (.env / .env.example)

All secrets come from the environment. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection (required) |
| `SECRET_KEY` | session/csrf signing (change in prod) |
| `APP_ENV` | dev \| prod |
| `BASE_URL` | public base URL |
| `LLM_PROVIDER` | openai \| ollama \| none (default none) |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI scoring/planning |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | local Ollama |
| `APOLLO_API_KEY` | Apollo enrichment |
| `HUNTER_API_KEY` | Hunter enrichment fallback |
| `SKRAPP_API_KEY` | Skrapp enrichment fallback |
| `TAVILY_API_KEY` / `SERPER_API_KEY` | web search |
| `GOOGLE_PLACES_API_KEY` | Google Places (Pro source) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | email; omitted = dev console logs reset links |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_MODE` | billing (test/live) |
| `LEADOPS_URL`, `LEADOPS_TOKEN` | optional LeadOps push |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | admin seed |
| `TRIAL_CREDITS`, `TRIAL_DAYS` | trial defaults (10 credits, 7 days) |
| `RATE_LIMIT_JOBS_PER_HOUR` | per-org job creation limit |

## Credits & plans

1 credit per lead delivered. Credits are reserved before a job and refunded if unused. Insufficient credits block job creation.

- **Starter:** 50 credits/mo, 1 seat, basic sources/scoring.
- **Pro:** 300 credits/mo, 5 seats, Places source, AI openers, API access, saved searches.

Plans live in the `plans` table and are seeded by `scripts.seed`. Never hardcode plan limits in code; read them from the plans table.

## Deployment (no Docker)

**Render/Railway:** `Procfile` + `render.yaml` (web + worker, managed Postgres). Release command: `alembic upgrade head && python -m scripts.seed`. Deploy = git push.

**VPS (Ubuntu):** `scripts/setup_vps.sh` installs Postgres, venv, deps, runs alembic + seed, creates systemd units `leadforge-web` and `leadforge-worker`, configures Caddy HTTPS, and sets up pg_dump backups. Use `scripts/update.sh` and `scripts/rollback.sh` for updates.

## Files

- `app/main.py` — FastAPI app, `/healthz`, routers
- `app/config.py` — pydantic-settings
- `app/db.py` — SQLAlchemy engine/session
- `app/models/` — SQLAlchemy models
- `app/services/` — planner, llm, sources, merge, enrich, score, quota, exporter, integrations
- `app/worker.py` — Postgres job queue (`SKIP LOCKED`) + scheduler
- `scripts/seed.py` — plans + admin seed
- `scripts/dev_db.py` — embedded local Postgres
- `alembic/` — migrations
- `tests/` — pytest suite
- `docs/` — ARCHITECTURE.md, DEPLOY.md, ADMIN.md
- `DECISIONS.md` — design decisions

## Notes

- The legacy Selenium/Chrome/Excel-datastore scraper (`lead_scraper.py`, `preflight.py`, `leadforge_single.py`, `scraper.env`) was removed. Excel/CSV is export-only.
- `KEY_MODE=platform` is implemented; `byo` (org-owned encrypted keys) is flagged TODO.
- Without API keys the app runs in rule-based/no-AI mode.
