"""
LinkedIn people search -> one Excel file (default: linkedin_leads.xlsx, set LEADS_FILE in .env).

Flow (by design):
1) You log in and set People search filters (keyword, location, 2nd, etc.) in Chrome.
2) You start Chrome with remote debugging, e.g.:
     "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
       --remote-debugging-port=9222 --user-data-dir="D:\\selenium\\li_profile"
3) This script attaches to that browser (session reuse), scrolls/paginates the *current*
   results, opens each profile with human-like delays, scrapes + company page, runs AI,
   writes one output file.

Env: .env.example — MAX_LEADS, ASK_MAX_LEADS=1, AI_BACKEND, OLLAMA_*, optional -n N on CLI.
"""

import os
import random
import sys
import time
from collections import OrderedDict

from scraper_core import (
    UNLOCKED_MESSAGE,
    build_chrome_options,
    click_next_search_page,
    close_except_handle,
    collect_profile_hrefs_on_page,
    detect_agency_type,
    extract_company_size_overview,
    extract_name_role_company,
    generate_problem_seen,
    generate_solution,
    is_company_page_locked_premium,
    is_premium_or_locked_profile,
    push_lead_to_backend,
    save_leads_file,
    scroll_search_page,
    _env_bool,
    _env_int,
    _env_str,
    pick_proxy_url,
)

# ======================
# CONFIG
# ======================
# Lead count: set MAX_LEADS in .env, or MAX_PROFILES (alias), or use --max-leads / ASK_MAX_LEADS=1
def _configured_max_leads() -> int:
    cap = _env_int("MAX_LEADS_CAP", 500)
    raw = _env_str("MAX_LEADS", None) or _env_str("MAX_PROFILES", None)
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 20
    else:
        n = 20
    return max(1, min(n, cap))


DELAY_MIN = int(os.environ.get("DELAY_MIN", "4"))
DELAY_MAX = int(os.environ.get("DELAY_MAX", "9"))
SCROLL_ROUNDS_PER_PAGE = int(os.environ.get("SCROLL_ROUNDS_PER_PAGE", "4"))
MAX_SEARCH_PAGES = int(os.environ.get("MAX_SEARCH_PAGES", "8"))
MAX_EXTRA_TABS = int(os.environ.get("MAX_EXTRA_TABS", "1"))

# Default: attach to your Chrome (manual login + filters). Set ATTACH_EXISTING_CHROME=0 to launch a new browser.
ATTACH_EXISTING_CHROME = _env_bool("ATTACH_EXISTING_CHROME", default=True) or _env_str(
    "ATTACH", ""
).lower() in ("1", "true", "yes")
REMOTE_DEBUG_PORT = _env_int("REMOTE_DEBUG_PORT", 9222)
START_URL = _env_str(
    "START_URL", "https://www.linkedin.com/search/results/people/"
) or "https://www.linkedin.com/search/results/people/"

# Single output: Excel only (no separate CSV). Name without app branding.
LEADS_FILE = _env_str("LEADS_FILE", "linkedin_leads.xlsx") or "linkedin_leads.xlsx"

LNN_BASE_URL = _env_str("LNN_BASE_URL", None) or _env_str("VITE_API_URL", None)
LNN_API_TOKEN = _env_str("LNN_API_TOKEN", None)
LNN_WORKSPACE_ID = int(os.environ.get("LNN_WORKSPACE_ID", "0") or 0)
LNN_IS_ADMIN = _env_bool("LNN_IS_ADMIN", default=False)
LNN_PUSH = _env_bool("LNN_PUSH", default=False)
ASK_MAX_LEADS = _env_bool("ASK_MAX_LEADS", default=False)


def human_delay() -> None:
    time.sleep(random.randint(DELAY_MIN, DELAY_MAX))


def cdp_anti_det(driver: object) -> None:
    if not ATTACH_EXISTING_CHROME:
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
                },
            )
        except Exception:
            pass


def build_profile_queue(driver, max_n: int) -> list[str]:
    ordered: "OrderedDict[str, None]" = OrderedDict()
    for page_i in range(MAX_SEARCH_PAGES):
        print(f"  [search] page {page_i + 1}/{MAX_SEARCH_PAGES}, scrolling...", flush=True)
        scroll_search_page(driver, SCROLL_ROUNDS_PER_PAGE)
        time.sleep(0.5)
        for h in collect_profile_hrefs_on_page(driver):
            if h not in ordered:
                ordered[h] = None
        print(
            f"  [search] collected {len(ordered)} unique /in/ links (cap {max_n})",
            flush=True,
        )
        if len(ordered) >= max_n:
            break
        if not click_next_search_page(driver):
            print("  [search] no more pages (or Next not found).", flush=True)
            break
        time.sleep(1.5)
    return list(ordered)[:max_n]


def _cap_extra_browser_windows(driver: object, search_handle: str) -> None:
    """Keep at most MAX_BROWSER_TABS windows (min 3: search + profile + company)."""
    cap = max(3, min(_env_int("MAX_BROWSER_TABS", 3), 10))
    for _ in range(24):
        handles = list(driver.window_handles)
        if len(handles) <= cap:
            try:
                driver.switch_to.window(search_handle)
            except Exception:
                pass
            return
        victim = None
        for w in reversed(handles):
            if w != search_handle:
                victim = w
                break
        if not victim:
            return
        try:
            driver.switch_to.window(victim)
            driver.close()
        except Exception:
            return


def scrape_one_lead(driver: object, profile_url: str, search_handle: str) -> dict:
    from selenium.common.exceptions import WebDriverException

    data: dict = {
        "Name": "",
        "Company": "",
        "Role": "",
        "Profile Link": profile_url,
        "Agency Type": "",
        "Team Size": "",
        "Problem Seen": "",
        "Last Active": "N/A",
        "Solution": "",
        "email_synthetic": None,
    }
    overview = ""

    def back_to_search() -> None:
        close_except_handle(driver, search_handle)

    try:
        driver.switch_to.window(search_handle)
        _cap_extra_browser_windows(driver, search_handle)
        driver.execute_script("window.open(arguments[0], '_blank');", profile_url)
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(1.4)
        human_delay()

        if is_premium_or_locked_profile(driver):
            print(f"🔒 Not unlocked / Premium: {profile_url}", flush=True)
            data["Problem Seen"] = UNLOCKED_MESSAGE
            data["Solution"] = f"— ({UNLOCKED_MESSAGE})"
            back_to_search()
            return data

        name, role, comp, clink = extract_name_role_company(driver)
        if not (name or "").strip():
            time.sleep(2.0)
            driver.execute_script("window.scrollTo(0, 500);")
            time.sleep(0.5)
            name, role, comp, clink = extract_name_role_company(driver)
        data["Name"] = name
        data["Role"] = role
        data["Company"] = comp
        data["Agency Type"] = detect_agency_type(f"{role} {comp} {name}")

        if clink and MAX_EXTRA_TABS > 0:
            driver.execute_script("window.open(arguments[0], '_blank');", clink)
            driver.switch_to.window(driver.window_handles[-1])
            time.sleep(1.0)
            human_delay()
            if is_company_page_locked_premium(
                driver
            ) or is_premium_or_locked_profile(driver):
                print("🔒 Company page not fully visible — team/overview skipped.", flush=True)
                data["Team Size"] = ""
                overview = ""
            else:
                data["Team Size"], overview = extract_company_size_overview(driver)
        else:
            data["Team Size"] = ""
            overview = ""
            if not (name or role):
                # Profile-only: still run AI on headline text
                overview = (data.get("Role", "") or "") + " " + (data.get("Company", "") or "")

        data["Problem Seen"] = generate_problem_seen(overview, role, comp)
        data["Solution"] = generate_solution(
            overview, data["Problem Seen"], name, comp, role
        )

        back_to_search()
        return data
    except WebDriverException as e:
        print("❌ WebDriver:", e, flush=True)
        back_to_search()
        data["Problem Seen"] = str(e)[:200]
        data["Solution"] = "— (error during scrape)"
        return data
    except Exception as e:  # noqa: BLE001
        print("❌ Error:", e, flush=True)
        back_to_search()
        data["Problem Seen"] = str(e)[:200]
        data["Solution"] = "— (error during scrape)"
        return data


def _clamp_leads(n: int) -> int:
    cap = _env_int("MAX_LEADS_CAP", 500)
    return max(1, min(int(n), cap))


def _ask_lead_limit_interactive() -> int:
    """After browser is ready: prompt for count (used when ASK_MAX_LEADS=1)."""
    cap = _env_int("MAX_LEADS_CAP", 500)
    base = _configured_max_leads()
    try:
        s = input(
            f"\nHow many leads to scrape? [default: {base}, max: {cap}] (Enter = default) "
        ).strip()
    except EOFError:
        s = ""
    if not s:
        return base
    try:
        n = int(s)
    except ValueError:
        print(f"  Invalid number - using default {base}.", flush=True)
        n = base
    return _clamp_leads(n)


def collect_linkedin_leads(
    lead_limit: int | None = None,
    *,
    ask_limit_after_browser_ready: bool = False,
) -> list[dict]:
    """
    Open browser (or attach), wait for user on People search, optionally prompt for N, then collect rows.
    Does not write files. Used by LeadPilot and by run().
    """
    options = build_chrome_options(
        attach=ATTACH_EXISTING_CHROME,
        remote_port=REMOTE_DEBUG_PORT,
    )
    from selenium import webdriver

    driver = webdriver.Chrome(options=options)
    if not ATTACH_EXISTING_CHROME:
        driver.get(START_URL)
    cdp_anti_det(driver)

    search_handle = driver.current_window_handle
    print(
        "\n"
        "1) In Chrome, log in if needed.\n"
        "2) Open **People** search, set **Keyword, Location, Network (e.g. 2nd)**, then results.\n"
        "3) Keep that **results** tab in focus / open.\n"
        "4) Press Enter here (attach mode does not navigate away).\n",
        flush=True,
    )
    input()

    if ask_limit_after_browser_ready:
        lead_limit = _ask_lead_limit_interactive()
    if lead_limit is None:
        lead_limit = _configured_max_leads()
    lead_limit = _clamp_leads(lead_limit)

    print(
        f"Lead limit this run: {lead_limit}  (MAX_LEADS / --max-leads / ask)\n",
        flush=True,
    )

    if not ATTACH_EXISTING_CHROME and "/search" not in (driver.current_url or ""):
        print("Tip: use a People search results URL (or set ATTACH_EXISTING_CHROME=1).", flush=True)

    search_handle = driver.current_window_handle
    data: list[dict] = []
    try:
        queue = build_profile_queue(driver, max_n=lead_limit * 2)
        if not queue:
            print("No /in/ links. Stay on the **people** results page with visible cards.", flush=True)
        to_do = queue[:lead_limit]
        print(f"\nScraping up to {len(to_do)} profiles (slower, human-like delays)...\n", flush=True)
        for i, url in enumerate(to_do, 1):
            print(f"--- [{i}/{len(to_do)}] {url}", flush=True)
            row = scrape_one_lead(driver, url, search_handle)
            if row and row.get("Profile Link"):
                data.append(row)
                label = (row.get("Name") or "").strip() or "(name not parsed)"
                print(f"  OK {label}", flush=True)
    finally:
        if not ATTACH_EXISTING_CHROME:
            try:
                driver.quit()
            except Exception:
                pass
        else:
            print("Attach mode: left your Chrome open.", flush=True)

    return data


def run(*, max_leads_override: int | None = None) -> None:
    if not _env_bool("SKIP_PREFLIGHT", default=False):
        from preflight import run_verification

        if not run_verification():
            print(
                "Preflight failed. Fix the items above, or set SKIP_PREFLIGHT=1 to continue "
                "without checks (not recommended).",
                flush=True,
            )
            sys.exit(1)

    pxy = pick_proxy_url()
    if pxy and not ATTACH_EXISTING_CHROME:
        print("Proxy (session):", pxy[:48], "...", flush=True)
    if ATTACH_EXISTING_CHROME and pxy:
        print("Note: proxy is ignored in attach mode (use system/VPN on host).", flush=True)

    if max_leads_override is not None:
        data = collect_linkedin_leads(
            _clamp_leads(max_leads_override), ask_limit_after_browser_ready=False
        )
    elif ASK_MAX_LEADS:
        data = collect_linkedin_leads(ask_limit_after_browser_ready=True)
    else:
        data = collect_linkedin_leads(_configured_max_leads(), ask_limit_after_browser_ready=False)

    if not data:
        print("No rows written. Check filters, 2nd-degree results, and that profiles load.")
        return

    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.path.basename(LEADS_FILE)
    )
    save_leads_file(data, out_path)
    print(f"\nSaved: {out_path}", flush=True)

    if LNN_PUSH and LNN_BASE_URL and LNN_API_TOKEN:
        if LNN_IS_ADMIN and LNN_WORKSPACE_ID < 1:
            print("LNN_IS_ADMIN=1 needs LNN_WORKSPACE_ID. Skipping API push.", flush=True)
        else:
            print("LNN_PUSH: posting...", flush=True)
            wid = LNN_WORKSPACE_ID if LNN_IS_ADMIN else max(1, LNN_WORKSPACE_ID)
            for row in data:
                ok, msg = push_lead_to_backend(
                    row,
                    LNN_BASE_URL,
                    LNN_API_TOKEN,
                    wid,
                    is_admin=LNN_IS_ADMIN,
                )
                print(" ", row.get("Name", ""), "->", "ok" if ok else msg[:120], flush=True)

    print(f"Done. {len(data)} lead(s) -> {os.path.basename(LEADS_FILE)} (Excel only).")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="LinkedIn people search scraper (attach to Chrome, export Excel).",
    )
    parser.add_argument(
        "-n",
        "--max-leads",
        type=int,
        default=None,
        metavar="N",
        help="Scrape at most N leads (overrides MAX_LEADS in .env and ASK_MAX_LEADS).",
    )
    parser.add_argument(
        "-v",
        "--verify-only",
        "--check",
        action="store_true",
        help="Run health checks only, then exit.",
    )
    parser.add_argument(
        "extra",
        nargs="?",
        default="",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.verify_only:
        from preflight import run_verification

        sys.exit(0 if run_verification() else 1)
    ex = (args.extra or "").strip()
    if ex:
        el = ex.lower()
        if el in ("verify", "check", "v"):
            from preflight import run_verification

            sys.exit(0 if run_verification() else 1)
        if ex.isdigit():
            run(max_leads_override=int(ex))
            sys.exit(0)
        print(f"Unknown argument: {ex!r}  (use: -n N, or: verify / check for preflight)", file=sys.stderr)
        sys.exit(2)
    run(max_leads_override=args.max_leads)
