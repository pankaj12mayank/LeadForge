"""
One-shot system checks before the LinkedIn scraper run.
Run standalone:  python preflight.py
Or:             python lead_scraper.py --verify-only
"""

from __future__ import annotations

import importlib
import os
import socket
import sys
import tempfile
from typing import Any

from scraper_core import (
    DEFAULT_OLLAMA_MODEL,
    SOLUTION_HEADER,
    get_ai_backend,
    get_solution_backend,
    save_leads_file,
    _env_bool,
    _env_int,
    _env_str,
    pick_proxy_url,
)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}", flush=True)


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}", flush=True)


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}", flush=True)


def _check_python() -> bool:
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        _fail(f"Python 3.10+ required (this is {v.major}.{v.minor})")
        return False
    _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    return True


def _check_imports(attach: bool, leads_file: str) -> bool:
    need = [
        "selenium",
        "pandas",
        "openpyxl",
        "httpx",
    ]
    for name in need:
        try:
            importlib.import_module(name)
            _ok(f"import {name}")
        except Exception as e:
            _fail(f"import {name}: {e!s}")
            return False
    try:
        importlib.import_module("dotenv")
        _ok("import dotenv (optional but recommended)")
    except Exception:
        _warn("python-dotenv not found - .env may not auto-load; pip install python-dotenv")
    if not attach:
        px = pick_proxy_url()
        if px:
            _ok(f"proxy will be used: {px[:50]}...")
    return True


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except OSError:
        return False


def _check_chrome_attach(port: int) -> bool:
    if not _port_open("127.0.0.1", port):
        _fail(
            f"Nothing listening on 127.0.0.1:{port} - start Chrome with "
            f'--remote-debugging-port={port} (see .env.example)'
        )
        return False
    _ok(f"Remote debugging port {port} is open (attach mode ready)")
    return True


def _check_ai() -> bool:
    b = get_ai_backend()
    s = get_solution_backend()
    _ok(f"AI_BACKEND={b!r}  SOLUTION_AI_BACKEND={s!r}")
    if b == "api" or s == "api":
        key = _env_str("OPENAI_API_KEY", None)
        if not key:
            _fail("AI_BACKEND or SOLUTION is api but OPENAI_API_KEY is empty")
            return False
        _ok("OPENAI_API_KEY is set")
        try:
            importlib.import_module("openai")
            _ok("import openai")
        except Exception as e:
            _fail(f"openai package: {e!s}")
            return False
    if b == "ollama" or s == "ollama":
        try:
            import httpx
        except Exception as e:
            _fail(f"httpx required for Ollama: {e!s}")
            return False
        base = (_env_str("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/")
        try:
            r = httpx.Client(timeout=8.0).get(f"{base}/api/tags")
        except Exception as e:
            _fail(f"Ollama not reachable at {base}: {e!s} - start: ollama serve")
            return False
        if r.status_code != 200:
            _fail(f"Ollama {base}/api/tags -> HTTP {r.status_code}")
            return False
        _ok(f"Ollama responds at {base}")
        model = _env_str("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL) or DEFAULT_OLLAMA_MODEL
        data = r.json() or {}
        names: list[str] = []
        for m in data.get("models", []):
            if isinstance(m, dict) and m.get("name"):
                names.append(m["name"])
        if not names:
            _warn("Ollama returned no models - run: ollama pull " + model.split(":")[0])
        elif not any(model in n or n.startswith(model) for n in names):
            _warn(
                f"Model {model!r} not obvious in ollama list. Available include: {names[:5]}... "
                f"Try: ollama pull {model}"
            )
        else:
            _ok(f"Ollama model {model!r} appears available")
    if b == "none" and s == "none":
        _warn("AI is off - Problem/Solution will use rules / placeholders only")
    return True


def _check_output_path(script_dir: str, leads_file: str) -> bool:
    out = os.path.join(script_dir, os.path.basename(leads_file))
    parent = os.path.dirname(os.path.abspath(out)) or "."
    if not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            _fail(f"Cannot create output directory {parent!r}: {e}")
            return False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=parent,
            prefix="._leadstest_",
            suffix=".tmp",
            delete=False,
        ) as t:
            tmp = t.name
        os.unlink(tmp)
    except OSError as e:
        _fail(f"Output folder not writable ({parent!r}): {e}")
        return False
    _ok(f"Output folder writable -> {out}")
    try:
        dummy: list[dict] = [
            {
                "Name": "Test",
                "Company": "Co",
                "Role": "Role",
                "Profile Link": "https://www.linkedin.com/in/test",
                "Agency Type": "Other",
                "Team Size": "",
                "Problem Seen": "—",
                "Last Active": "N/A",
                "Solution": "—",
            }
        ]
        test_path = out + ".verify_tmp.xlsx"
        save_leads_file(dummy, test_path)
        os.unlink(test_path)
        _ok("save_leads_file() smoke test passed")
    except Exception as e:
        _fail(f"save_leads_file() failed: {e!s}")
        return False
    return True


def _check_remote_api_push() -> bool:
    if not _env_bool("LNN_PUSH", False):
        _ok("LNN_PUSH=0 (remote API push off)")
        return True
    base = _env_str("LNN_BASE_URL", None) or _env_str("VITE_API_URL", None)
    token = _env_str("LNN_API_TOKEN", None)
    if not base or not token:
        _fail("LNN_PUSH=1 but LNN_BASE_URL or LNN_API_TOKEN missing")
        return False
    admin = _env_bool("LNN_IS_ADMIN", False)
    wid = _env_int("LNN_WORKSPACE_ID", 0)
    if admin and wid < 1:
        _fail("LNN_IS_ADMIN=1 requires LNN_WORKSPACE_ID >= 1")
        return False
    _ok("LNN_* env looks complete for LNN_PUSH")
    try:
        import httpx

        r = httpx.Client(timeout=5.0).get(base.rstrip("/") + "/docs")
        if r.status_code < 500:
            _ok(f"Backend {base!r} responds (e.g. /docs or /openapi.json)")
        else:
            _warn(f"Backend returned HTTP {r.status_code} - check URL and server")
    except Exception as e:
        _warn(f"Could not reach {base!r} ({e!s}) - start server if you need push")
    return True


def run_verification() -> bool:
    """Run all checks. Return True if no hard failures (warnings allowed)."""
    here = os.path.dirname(os.path.abspath(__file__))
    port = _env_int("REMOTE_DEBUG_PORT", 9222)
    attach = _env_bool("ATTACH_EXISTING_CHROME", default=True) or _env_str(
        "ATTACH", ""
    ).lower() in ("1", "true", "yes")
    leads = _env_str("LEADS_FILE", "linkedin_leads.xlsx") or "linkedin_leads.xlsx"

    print("\n========== PREFLIGHT ==========\n", flush=True)
    section = "1) Python & imports"
    print(section, flush=True)
    if not _check_python():
        return False
    if not _check_imports(attach, leads):
        return False

    print("\n2) Chrome / Selenium", flush=True)
    if attach:
        if not _check_chrome_attach(port):
            return False
    else:
        _ok("Launch mode: script will start Chrome (ensure chromedriver matches your Chrome)")

    print("\n3) AI (Ollama / API)", flush=True)
    if not _check_ai():
        return False

    print("\n4) Output file", flush=True)
    if not _check_output_path(here, leads):
        return False

    print("\n5) Optional API push (LNN_*)", flush=True)
    if not _check_remote_api_push():
        return False

    sh = SOLUTION_HEADER[:50] + "..." if len(SOLUTION_HEADER) > 50 else SOLUTION_HEADER
    _ok(f"export column for Solution: {sh}")
    print("\n========== PREFLIGHT OK ==========\n", flush=True)
    return True


if __name__ == "__main__":
    sys.exit(0 if run_verification() else 1)
