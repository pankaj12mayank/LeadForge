# Architecture

LeadForge is a monolithic FastAPI app backed by PostgreSQL only (no Redis/Celery/Docker).

## Layers
- `app/main.py` — FastAPI factory, routers, middleware, global error handler, `/healthz`.
- `app/config.py` — pydantic-settings, single `.env`.
- `app/db.py` — SQLAlchemy 2.0 sync engine/session (psycopg2).
- `app/models/` — SQLAlchemy models (users, organizations, plans, subscriptions, credit_ledger, searches, jobs, leads, webhook_events, audit_log, api_keys, org_secrets).
- `app/auth/` — signup/login/logout/password reset, argon2, signed session cookie, CSRF, deps (`current_user`, `current_org_id`, `require_admin`).
- `app/routers/` — landing, auth, dashboard, searches, leads, billing, admin, api.
- `app/services/` — planner, llm, sources (base/apollo/websearch/places), merge, enrich, score, quota, exporter, integrations.
- `app/worker.py` — Postgres queue (`SELECT ... FOR UPDATE SKIP LOCKED`) + scheduler, `python -m app.worker`.

## Data flow
1. User submits one query → `searches` row + `jobs` row (queued).
2. Worker claims job → `planner.plan_query` (LLM or rule-based) → `sources` run concurrently via `asyncio.gather` (one failing source never fails the job).
3. `merge.merge_incoming` then dedupe against existing org leads.
4. Credits reserved upfront (target count); unused refunded after delivery; insufficient credits → job failed.
5. `enrich` waterfall (Apollo → Hunter → Skrapp, stop at first hit). `score` (LLM or rule-based, 0–100, hot/warm/cold; Pro gets opener).
6. Leads inserted into `leads`; job marked done/failed with retry (up to 3) and stale-running recovery after 15 min.

## Security
- argon2 passwords, signed HttpOnly SameSite=Lax session cookie, CSRF on forms.
- ORM-only queries; org-scoped reads; per-org rate limiting on job creation.
- Export formula-injection sanitization (`=+-@` prefixed).
- Secrets from env only; never logged.
