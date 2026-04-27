# LeadPilot v3

Production-oriented layout: **scrape → enrich → score → export**, with clear failure modes and no fake API clients.

## Layout

```
Linkedin/
  lead_scraper.py          # Legacy single-purpose CLI (Excel only)
  scraper_core.py         # LinkedIn DOM + Ollama/OpenAI + Excel helper
  preflight.py
  leadpilot/
    __init__.py
    __main__.py           # python -m leadpilot
    main.py               # Orchestrator
    scraper.py            # Calls collect_linkedin_reads
    enrichment.py         # Apollo + Skrapp (httpx + retries)
    scoring.py            # Weighted score + optional GPT
    export.py             # .xlsx + optional .json
  leadpilot_single.py     # One-file entry (MVP)
```

## APIs (you must verify against your plan)

- **Apollo.io** — `POST {APOLLO_BASE_URL}/v1/people/match` with JSON including `linkedin_url` / name / company. Some plans use a header for the key: set `APOLLO_USE_HEADER_KEY=1` and put the key in `X-Api-Key`.
- **Skrapp** — `GET` to `{SKRAPP_BASE_URL}/v2/find` with your access header (`SKRAPP_TOKEN_HEADER`, default `X-Access-Key`). Exact query params can differ; adjust `enrichment.py` to match your dashboard.

If keys are missing, rows get `enrichment_status=skipped_config` or `failed` and the pipeline still completes.

## Scoring model (rule default)

| Factor | Max pts |
|--------|--------|
| Role (decision-maker / seniority) | 30 |
| Company size band (10–200 ideal) | 20 |
| Problem intensity (text) | 25 |
| Digital maturity gap (overview) | 15 |
| “Activity” (placeholder if Last Active is generic) | 10 |

Optional: `SCORING_USE_GPT=1` + `OPENAI_API_KEY` refines problem text. `SCORING_GPT_SCORE=1` allows GPT to override the numeric score (use with care).

## Reliability

- Retries: `@with_retries` on external HTTP (3 attempts, exponential backoff).
- LinkedIn: unchanged selectors live in `scraper_core` / `lead_scraper` — do not fork lightly.
- Window cap: `MAX_BROWSER_TABS` (default 3) trims extra windows before each profile (search + profile + company).

## Future extensions

- CRM: add `leadpilot/integrations/hubspot.py` implementing a thin client + map `export` columns.
- Same pattern for Notion, cold email, and multi-account queues (dedicated `worker` process + task queue design).

## Test mode

- `LEADPILOT_TEST=1` or `python leadpilot_single.py --test` — caps scrape count at 10.
- `DEBUG=1` — more logging from `leadpilot.utils.get_logger`.
