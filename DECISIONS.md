# DECISIONS (LeadForge)

- **Database:** PostgreSQL only. Local dev/tests use `pgserver` (embedded Postgres) started via `scripts/dev_db.py` because no system Postgres is installed on this Windows host. `.env` points `DATABASE_URL` to the pgserver instance URL.
- **ORM:** SQLAlchemy 2.0 sync session (psycopg2). FastAPI routes are async but call sync DB in threads via `Depends(get_db)`.
- **Sessions:** signed session cookie (`itsdangerous`, HttpOnly, Secure in prod, SameSite=Lax). CSRF token per form via hidden field.
- **Passwords:** argon2 via `argon2-cffi`.
- **Auth flows:** signup creates user + org + starter trial (7 days, 10 credits). Login/logout/reset via email SMTP; if SMTP missing, reset link is logged to console (dev mode).
- **AI:** default `LLM_PROVIDER=none` (rule-based placeholders) so the app runs without Ollama/OpenAI. OpenAI/Ollama provider abstraction in `app/services/llm.py` with JSON schema validation + retries.
- **Queue/scheduler:** Postgres-backed jobs table with `SELECT ... FOR UPDATE SKIP LOCKED`; worker run as `python -m app.worker`.
- **Sources:** async `Source` interface with tenacity retry/backoff; failures in one source don't fail a job. Pro-only sources gated by plan features.
- **Credits:** 1 credit per lead delivered; reserved before job, refunded unused; insufficient credits blocks job.
- **KEY_MODE:** `platform` implemented; `byo` left behind flag with TODO (no org_secrets usage yet).
- **Export:** xlsx/csv via openpyxl; CSV formula injection guarded by prefixing `=+-@` cells.
- **Deleted legacy:** `lead_scraper.py`, `preflight.py`, `leadforge_single.py`, `scraper.env`, `leadforge/`, `scraper_core.py`, Selenium/Chrome remote debugging, Excel-as-datastore.
