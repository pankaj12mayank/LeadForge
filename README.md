# LinkedIn lead scraper

People-search results → one **Excel** file (`linkedin_leads.xlsx` by default), with optional **Ollama** or **OpenAI** for “Problem seen” and “Solution”, and optional **HTTP API** to push leads into your app.

## LeadPilot v3 (scrape + enrichment + scoring)

Modular pipeline in the `leadpilot/` package:

| Step | Module | Notes |
|------|--------|--------|
| LinkedIn | `leadpilot/scraper.py` | Wraps `collect_linkedin_leads()` (same Selenium layer as `lead_scraper.py`) |
| Enrichment | `leadpilot/enrichment.py` | **Apollo.io** then **Skrapp** fallback; set `APOLLO_API_KEY`, `SKRAPP_API_KEY` |
| Scoring | `leadpilot/scoring.py` | Weighted 0–100 + Hot/Warm/Cold; optional GPT via `OPENAI_API_KEY`, `SCORING_GPT_SCORE=1` |
| Export | `leadpilot/export.py` | Excel + optional JSON |

**Run (from `Linkedin/`):**

```bash
python leadpilot_single.py --test -n 5 -o leadpilot_runs.xlsx
# or
python -m leadpilot --help
```

- `--test` sets `LEADPILOT_TEST=1` (caps leads at 10) and enables verbose logging.
- `--skip-enrich` / `--skip-scoring` for dry runs.
- `LEADPILOT_PREFLIGHT=0` skips the same health checks as the legacy scraper if you only want API steps.

**Env (add to `scraper.env` or `.env`):** `APOLLO_API_KEY`, `SKRAPP_API_KEY` (and optional `APOLLO_BASE_URL`, `SKRAPP_BASE_URL`), `ENRICHMENT_ENABLED=0` to turn enrichment off, `LEADPILOT_OUT_XLSX` for default output path.

See **`LEADPILOT.md`** for architecture and API notes.

## Quick start

1. **Python 3.10+** and dependencies:

   ```bash
   cd Linkedin
   pip install -r requirements.txt
   ```

2. **Config — keep `.env.example`, `.env`, and `scraper.env` in sync**

   | File | Purpose |
   |------|--------|
   | **`.env.example`** | Full template (all options + comments). Copy when setting up a new machine. |
   | **`.env`** | Your local values (gitignored). Same keys as `scraper.env` by default. |
   | **`scraper.env`** | Same content as `.env`, but **no leading dot** so it’s easy to spot in Explorer. |

   **Load order:** `.env` first, then **`scraper.env`** (it **overrides** duplicate keys). Put API keys in either file; if both exist, prefer editing **`scraper.env`** so secrets stay out of `.env` if you use tooling that only reads `.env`.

3. **Chrome with remote debugging** (recommended — you log in and set filters yourself):

   ```text
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\selenium\li_profile"
   ```

   Log in to LinkedIn, open **People** search, set keyword / location / **2nd** connections, show results.

4. **Run**

   ```bash
   python lead_scraper.py
   ```

   First run executes **preflight** checks (Chrome port, Ollama/API, writable folder). Use `SKIP_PREFLIGHT=1` only if you must.

### CLI

| Command | Meaning |
|--------|---------|
| `python lead_scraper.py` | Full run |
| `python lead_scraper.py -n 25` | At most **25** leads (overrides `MAX_LEADS` and the interactive prompt) |
| `python lead_scraper.py 25` | Same as `-n 25` |
| `python lead_scraper.py --verify-only` | Health checks only (`--check` / `-v` also work) |
| `python preflight.py` | Same as verify-only |

### Environment variables (main)

| Variable | Meaning |
|----------|---------|
| `ATTACH_EXISTING_CHROME` | `1` = attach to port `REMOTE_DEBUG_PORT` (default). `0` = Selenium starts a new Chrome. |
| `MAX_LEADS` | How many profiles to scrape (alias: `MAX_PROFILES`). |
| `MAX_LEADS_CAP` | Hard cap (default 500). |
| `ASK_MAX_LEADS` | `1` = after the browser is ready, ask how many leads (unless `-n` is passed). |
| `LEADS_FILE` | Output filename, e.g. `linkedin_leads.xlsx`. |
| `AI_BACKEND` | `ollama` (default), `api` (OpenAI-compatible), or `none`. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local Ollama server and model. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | When `AI_BACKEND=api`. |
| `LNN_*` | Optional push to a backend that accepts the project’s lead API (see your app’s docs). |

See **`.env.example`** for the full list.

## Output

- **One** `.xlsx` file (columns include Name, Company, Role, Profile link, agency type, team size, problem, last active, solution).
- No separate CSV.

## Troubleshooting

- **Preflight fails on port 9222** — Start Chrome with `--remote-debugging-port=9222`, or set `ATTACH_EXISTING_CHROME=0` to let the script launch Chrome (LinkedIn login is harder in that mode).
- **Ollama errors** — Run `ollama serve` and `ollama pull <model>` (e.g. `qwen2.5:7b`), or set `AI_BACKEND=none` for rule-based text only.
- **`.env` not showing in Explorer** — Use **`scraper.env`** in the same folder; the code loads both.

## License

Use at your own risk; respect LinkedIn’s terms and applicable laws.
