"""
LinkedIn people-search scraper helpers: DOM collection, scroll/pagination,
Premium gates, optional Ollama/OpenAI, Excel export, optional remote API push, proxy.
"""

from __future__ import annotations

import os
import random
import re
import time
import uuid
from typing import Any

# --- Load env: .env then scraper.env (later overrides; scraper.env has no leading dot = easy to see in Explorer) ---
def _load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    _d = os.path.dirname(os.path.abspath(__file__))
    for _name in (".env", "scraper.env"):
        _f = os.path.join(_d, _name)
        if os.path.isfile(_f):
            try:
                load_dotenv(_f, override=True)
            except Exception:
                pass
    _cw = os.path.normpath(os.getcwd())
    if _cw != os.path.normpath(_d):
        for _name in (".env", "scraper.env"):
            _f = os.path.join(_cw, _name)
            if os.path.isfile(_f):
                try:
                    load_dotenv(_f, override=True)
                except Exception:
                    pass


_load_dotenv_files()

# Lazy imports in functions: selenium, httpx, openai

UNLOCKED_MESSAGE = (
    "Can't capture: profile / company is not fully unlocked (Premium or network required)."
)

# One output file — canonical column keys (header row = user-facing names in save function)
# AI_BACKEND: ollama (default) | api | none
# Ollama: http://127.0.0.1:11434 — use a strong general model, e.g. qwen2.5:7b, llama3.1:8b
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _env_str(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key, "").strip()
    return v if v else default


def _env_int(key: str, default: int) -> int:
    v = _env_str(key, "")
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = _env_str(key, "")
    if not v:
        return default
    v = v.lower()
    if v in ("0", "false", "no", "n", "off"):
        return False
    if v in ("1", "true", "yes", "y", "on"):
        return True
    return default


def pick_proxy_url() -> str | None:
    single = _env_str("PROXY_URL", None)
    if single:
        return single
    path = _env_str("PROXY_LIST_FILE", None)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return None
    line = random.choice(lines)
    if "://" in line:
        return line
    if ":" in line:
        h, p = line.rsplit(":", 1)
        return f"http://{h.strip()}:{p.strip()}"
    return None


def build_chrome_options(*, attach: bool, remote_port: int) -> Any:
    """If attach, only debugger_address. Else optional user data dir, proxy, stealth flags."""
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    if attach:
        options.debugger_address = f"127.0.0.1:{remote_port}"
        return options
    user_data = _env_str("CHROME_USER_DATA_DIR", None)
    if user_data:
        # Use a *copy* of your profile to load extensions; close all Chrome on this dir first.
        options.add_argument(f"--user-data-dir={os.path.expanduser(user_data)}")
    if _env_bool("CHROME_START_MAXIMIZED", True):
        options.add_argument("--start-maximized")
    proxy = pick_proxy_url()
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")
    if _env_str("CHROME_EXPERIMENTAL", "1") != "0":
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
    return options


def normalize_in_url(h: str) -> str | None:
    if not h or "linkedin.com" not in h and "/in/" not in h:
        return None
    if "linkedin.com/in/" not in h and "/in/" not in h:
        return None
    if "linkedin.com/company/" in h:
        return None
    m = re.search(r"(https?://[^/]+/in/[^/]+)", h, re.I)
    if not m:
        return None
    u = m.group(1)
    u = re.sub(r"[\?#].*$", "", u)
    slug = u.split("/in/")[-1]
    if not slug or len(slug) < 2:
        return None
    if slug in ("in", "unavailable", "login"):
        return None
    return u.rstrip("/")


def collect_profile_hrefs_on_page(driver) -> list[str]:
    from selenium.webdriver.common.by import By

    seen, out = set(), []
    selectors = (
        "main a[href*='/in/']",
        "ul a[href*='/in/']",
        "a[href*='/in/']",
    )
    for sel in selectors:
        for a in driver.find_elements(By.CSS_SELECTOR, sel):
            h = normalize_in_url(a.get_attribute("href") or "")
            if h and h not in seen:
                seen.add(h)
                out.append(h)
    return out


def scroll_search_page(driver, rounds: int) -> None:
    for _ in range(max(0, rounds)):
        driver.execute_script(
            """
            const pick = () =>
              document.querySelector('.scaffold-layout__list, .search-results-container, main, [role="main"]')
              || document.scrollingElement;
            const m = pick();
            if (m) { m.scrollTo(0, m.scrollHeight + 2); }
            """
        )
        time.sleep(random.uniform(1.0, 2.0))


def click_next_search_page(driver) -> bool:
    from selenium.webdriver.common.by import By

    for sel in (
        "button.artdeco-pagination__button--next",
        "button[aria-label='Next']",
    ):
        try:
            b = driver.find_element(By.CSS_SELECTOR, sel)
            if not b.is_displayed():
                continue
            if b.get_attribute("disabled") is not None or "disabled" in (
                b.get_attribute("class") or ""
            ).lower():
                return False
            b.click()
            time.sleep(1.5)
            return True
        except Exception:
            continue
    return False


def ensure_first_tab(driver) -> None:
    while len(driver.window_handles) > 1:
        try:
            driver.switch_to.window(driver.window_handles[-1])
            driver.close()
        except Exception:
            break
    if driver.window_handles:
        driver.switch_to.window(driver.window_handles[0])


def close_except_handle(driver, keep: str) -> None:
    """Close every tab/window except *keep* (e.g. your people-search tab)."""
    for _ in range(25):
        cur = list(driver.window_handles)
        if len(cur) <= 1:
            break
        to_close = next((h for h in reversed(cur) if h != keep), None)
        if not to_close:
            break
        try:
            driver.switch_to.window(to_close)
            driver.close()
        except Exception:
            break
    try:
        if keep in driver.window_handles:
            driver.switch_to.window(keep)
    except Exception:
        if driver.window_handles:
            try:
                driver.switch_to.window(driver.window_handles[0])
            except Exception:
                pass


def is_premium_or_locked_profile(driver) -> bool:
    from selenium.webdriver.common.by import By

    url = (driver.current_url or "").lower()
    if "authwall" in url or "/uas/login" in url or url.rstrip("/").endswith("linkedin.com/login"):
        return True
    try:
        page = (driver.find_element(By.TAG_NAME, "body").text or "")[:16000]
    except Exception:
        return True
    p = page.lower()
    if any(
        k in p
        for k in (
            "this profile is not available",
            "isn't available",
            "is not available",
            "isn’t available",
            "out of your network to view this profile",
            "sign in to view the full post",
        )
    ):
        return True
    # Premium / Sales Navigator upsell on profile
    if (
        re.search(
            r"(upgrade to|unlock this profile|premium to view|try premium|sales navigator)",
            p,
        )
        and re.search(
            r"(get full|see who|view full|unlock this|subscribe)",
            p,
        )
    ):
        return True
    try:
        h1e = driver.find_element(By.CSS_SELECTOR, "h1, h1.inline")
        t = (h1e.text or "").strip()
        if t.lower() == "linkedin member" and len(t) < 3:
            return True
    except Exception:
        pass
    return False


def is_company_page_locked_premium(driver) -> bool:
    from selenium.webdriver.common.by import By

    if not driver.find_elements(By.CSS_SELECTOR, "main, [role='main']"):
        return True
    return is_premium_or_locked_profile(driver)


def extract_name_role_company(driver) -> tuple[str, str, str, str]:
    from selenium.common.exceptions import NoSuchElementException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    name, role, company, company_link = "", "", "", ""
    try:
        WebDriverWait(driver, 16).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1, main, [role='main']"))
        )
    except Exception:
        pass
    time.sleep(0.3)
    try:
        driver.execute_script("window.scrollTo(0, 120);")
        time.sleep(0.2)
    except Exception:
        pass
    for sel in (
        "h1.text-heading-xlarge",
        "main h1",
        "section.top-card-layout h1",
        ".pv-text-details__left-panel h1",
        "h1.inline",
        "h1",
    ):
        try:
            n = driver.find_element(By.CSS_SELECTOR, sel)
            t = (n.text or "").replace("\n", " ").strip()
            if t and len(t) < 300 and t.lower() not in ("linkedin", "search"):
                name = t
                break
        except NoSuchElementException:
            continue
    for sel in (
        "div.text-body-medium",
        "div.text-body-medium.break-words",
        "span.text-body-small",
        "div[class*='text-body-medium']",
    ):
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for n in els[:8]:
                t = (n.text or "").strip()
                if not t or len(t) > 280:
                    continue
                if t == name or t.lower() in ("message", "connect", "more", "follow"):
                    continue
                if any(x in t.lower() for x in ("connection", "follower", "mutual")):
                    continue
                role = t
                break
            if role:
                break
        except NoSuchElementException:
            pass
    # Company: prefer top-card / experience area; first company link with visible name
    candidates: list[tuple[str, str]] = []
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/company/']"):
        c = a.get_attribute("href") or ""
        if "linkedin.com/company/" not in c or "/in/" in c:
            continue
        c = c.split("?")[0]
        label = (a.text or "").strip() or (a.get_attribute("aria-label") or "").strip() or ""
        if len(label) > 80:
            continue
        if label and not re.match(r"^[\d,\s]+(followers?|employees?)?$", label, re.I):
            candidates.append((label, c))
    for label, c in candidates:
        if label:
            company, company_link = label, c
            break
    if not company_link and candidates:
        company, company_link = candidates[0][0], candidates[0][1]
    return name, role, company, company_link


def extract_company_size_overview(driver) -> tuple[str, str]:
    from selenium.webdriver.common.by import By

    team_size, overview = "", ""
    time.sleep(0.3)
    try:
        driver.execute_script("window.scrollTo(0, 400);")
    except Exception:
        pass
    dts = driver.find_elements(
        By.XPATH,
        "//dt[contains(.,'Company size')]|//h3[contains(.,'Company size')]"
        "|//span[contains(.,'Company size')]|//div[contains(.,'Company size')]",
    )
    for dt in dts:
        t0 = (dt.text or "").strip()
        if "size" in t0.lower() or "employees" in t0.lower() or "company" in t0.lower():
            try:
                p = driver.execute_script("return arguments[0].closest('dl, div, li');", dt)
            except Exception:
                p = None
            if p:
                try:
                    sibs = p.find_elements(By.XPATH, ".//dd[1] | .//span[2] | following-sibling::*[1]")
                except Exception:
                    sibs = []
                for s in sibs:
                    tx = (s.text or "").strip()
                    if tx and (re.search(r"\d|employee|size|\+", tx, re.I) or len(tx) < 120):
                        team_size = tx
                        break
    if not team_size:
        for xp in (
            "//dt[contains(translate(.,'SIZE','size'),'size')]/following-sibling::dd[1]",
            "//*[contains(.,'Company size')]/following-sibling::*[1]",
        ):
            try:
                el = driver.find_element(By.XPATH, xp)
                tx = (el.text or "").strip()
                if tx and len(tx) < 200:
                    team_size = tx
                    break
            except Exception:
                pass
    for sel in (
        "section.org-about-module p",
        "div.org-about-us-organization-description p",
        "p.break-words",
        "p[class*='break-words']",
        "div.org-top-card-summary-info-list + * p",
        "span[dir='ltr'] p",
    ):
        try:
            for p in driver.find_elements(By.CSS_SELECTOR, sel)[:4]:
                t = (p.text or "").strip()
                if len(t) > 50:
                    overview = t
                    break
            if overview:
                break
        except Exception:
            pass
    return team_size, overview


def rule_based_problems(overview: str) -> str:
    overview = (overview or "").lower()
    problems: list[str] = []
    if "growing" in overview:
        problems.append("Scaling issues")
    if overview and "digital" not in overview and len(overview) > 50:
        problems.append("Weak digital presence")
    if "startup" in overview:
        problems.append("Lack of automation / early-stage ops")
    return ", ".join(problems[:3]) or "—"


def get_ai_backend() -> str:
    b = (_env_str("AI_BACKEND", "ollama") or "ollama").lower()
    if b in ("api", "openai", "gpt", "open_ai"):
        return "api"
    if b in ("ollama", "local", "lmstudio"):
        return "ollama"
    return "none"


def ollama_chat(user_prompt: str, system_prompt: str | None = None) -> str | None:
    try:
        import httpx
    except Exception:
        return None
    base = (_env_str("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/")
    model = _env_str("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL) or DEFAULT_OLLAMA_MODEL
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    try:
        with httpx.Client(timeout=120.0) as c:
            r = c.post(
                f"{base}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
            )
        if not r.is_success:
            return f"(Ollama error: {r.status_code} {r.text[:120]})"
        data = r.json()
        out = ""
        if isinstance(data.get("message"), dict):
            out = (data["message"].get("content") or "").strip()
        if not out and data.get("response"):
            out = str(data["response"]).strip()
        return out or None
    except Exception as e:
        return f"(Ollama: {e!s})"


def openai_chat(user_prompt: str, system_prompt: str | None = None) -> str | None:
    key = _env_str("OPENAI_API_KEY", None)
    if not key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None
    model = _env_str("OPENAI_MODEL", DEFAULT_OPENAI_MODEL) or DEFAULT_OPENAI_MODEL
    client = OpenAI(
        api_key=key,
        base_url=_env_str("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    try:
        msgs: list[dict] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": user_prompt})
        r = client.chat.completions.create(
            model=model, messages=msgs, max_tokens=500, temperature=0.4
        )
        return (r.choices[0].message.content or "").strip() or None
    except Exception as e:
        return f"(API: {e!s})"


def get_solution_backend() -> str:
    s = _env_str("SOLUTION_AI_BACKEND", None)
    if not s:
        return get_ai_backend()
    s = s.lower()
    if s in ("api", "openai", "gpt"):
        return "api"
    if s in ("ollama", "local", "default"):
        return "ollama"
    if s == "none":
        return "none"
    return get_ai_backend()


def generate_problem_seen(overview: str, role: str, company: str) -> str:
    b = get_ai_backend()
    if b == "none":
        return rule_based_problems(overview)
    system = (
        "You help B2B sales. Reply with 1-3 very short English phrases: likely pain points or opportunities. "
        "If not enough to infer, reply exactly: —"
    )
    user = f"Role: {role or '—'}\nCompany: {company or '—'}\nCompany overview (if any):\n{(overview or '')[:8000]}"
    out = ollama_chat(user, system) if b == "ollama" else openai_chat(user, system)
    if not out or out.startswith("(") or "error" in out[:30].lower():
        return rule_based_problems(overview)
    if out.strip() in ("—", "-"):
        return rule_based_problems(overview)
    return out.strip()[:2000]


def generate_solution(
    overview: str,
    problem_seen: str,
    name: str,
    company: str,
    role: str,
) -> str:
    b = get_solution_backend()
    if b == "none":
        return "— (set SOLUTION_AI_BACKEND=ollama or API)"
    system = (
        "You are a B2B sales assistant. Write 2-4 short sentences: a specific outreach angle, "
        "what to offer, and one question to ask. No flattery, no 'hope this finds you well'. English only."
    )
    user = (
        f"Name: {name or '—'}\nRole: {role or '—'}\nCompany: {company or '—'}\n"
        f"Angles / problems: {problem_seen or '—'}\nCompany blurb: {(overview or '')[:5000]}"
    )
    out = ollama_chat(user, system) if b == "ollama" else openai_chat(user, system)
    if not out or (out.startswith("(") and "Ollama" in out) or (out.startswith("(") and "API:" in out):
        return (out or "—")[:2000] if out else "—"
    return out.strip()[:5000]


def detect_agency_type(text: str) -> str:
    text = (text or "").lower()
    if "seo" in text:
        return "SEO"
    if "ads" in text or "performance" in text:
        return "Ads"
    if "creative" in text or "branding" in text:
        return "Creative"
    return "Other"


def push_lead_to_backend(
    lead: dict,
    base_url: str,
    token: str,
    workspace_id: int,
    *,
    is_admin: bool = False,
) -> tuple[bool, str]:
    try:
        import httpx
    except Exception as e:
        return False, str(e)
    email = lead.get("email_synthetic") or f"import-{uuid.uuid4().hex[:22]}@ws{workspace_id}.invalid"  # noqa: E501
    payload: dict = {
        "name": (lead.get("Name") or "Unknown")[:255],
        "email": email,
        "status": "new",
        "company": (lead.get("Company") or None) or None,
        "role_title": (lead.get("Role") or None) or None,
        "profile_link": (lead.get("Profile Link") or None) or None,
        "agency_type": (lead.get("Agency Type") or None) or None,
        "team_size_estimate": (lead.get("Team Size") or None) or None,
        "problem_seen": (lead.get("Problem Seen") or None) or None,
        "last_active_display": (lead.get("Last Active") or None) or None,
        "solution": (lead.get("Solution") or None) or None,
    }
    url = base_url.rstrip("/") + "/leads"
    if is_admin:
        if not workspace_id:
            return False, "LNN admin requires LNN_WORKSPACE_ID"
        params = f"?workspace_id={workspace_id}"
    else:
        params = ""  # workspace comes from the JWT
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.post(
                f"{url}{params}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.is_success:
            return True, r.text[:200]
        return False, f"{r.status_code} {r.text[:500]}"
    except Exception as e:
        return False, str(e)


# Public export header (single file). Solution column explains Ollama vs API switch.
SOLUTION_HEADER = (
    "Solution (AI: Ollama by default; switch to OpenAI: AI_BACKEND=api in .env)"
)


def _row_to_export(r: dict) -> dict:
    return {
        "Name": (r.get("Name") or "").strip(),
        "Company": (r.get("Company") or "").strip(),
        "Role": (r.get("Role") or "").strip(),
        "Profile Link": (r.get("Profile Link") or "").strip(),
        "Agency Type (SEO / Ads / Creative)": (r.get("Agency Type") or "").strip(),
        "Team Size (estimate)": (r.get("Team Size") or "").strip(),
        "Problem Seen": (r.get("Problem Seen") or "").strip(),
        "Last Active": (r.get("Last Active") or "N/A").strip(),
        SOLUTION_HEADER: (r.get("Solution") or "").strip(),
    }


def save_leads_file(rows: list[dict], path: str) -> None:
    """Single export format: Excel .xlsx only (opens cleanly in Excel / import elsewhere)."""
    p = path.strip()
    if not p.lower().endswith(".xlsx"):
        p = re.sub(r"\.(csv|xlsx)$", "", p, flags=re.I) + ".xlsx"
    try:
        import pandas as pd
    except Exception as e:
        raise RuntimeError("Export needs: pip install pandas openpyxl") from e
    if not rows:
        return
    df = pd.DataFrame([_row_to_export(r) for r in rows])
    df.to_excel(p, index=False, engine="openpyxl")


def problem_seen_line(overview: str, role: str, company: str) -> str:
    return generate_problem_seen(overview, role, company)
