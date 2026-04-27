"""
Shared helpers: logging, retries, parsing, delays.
Keep this file free of Selenium so tests can import it without a browser.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

T = TypeVar("T")

# ---- env (duplicated minimal set to avoid import cycles) ----
def env_bool(key: str, default: bool = False) -> bool:
    v = (os.environ.get(key) or "").strip().lower()
    if not v:
        return default
    if v in ("0", "false", "no", "n", "off"):
        return False
    if v in ("1", "true", "yes", "y", "on"):
        return True
    return default


def env_int(key: str, default: int) -> int:
    v = (os.environ.get(key) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def get_logger(name: str) -> logging.Logger:
    level = logging.DEBUG if env_bool("DEBUG", False) else logging.INFO
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        log.addHandler(h)
    log.setLevel(level)
    return log


def human_sleep(min_s: float | None = None, max_s: float | None = None) -> None:
    lo = min_s if min_s is not None else float(env_int("DELAY_MIN", 4))
    hi = max_s if max_s is not None else float(env_int("DELAY_MAX", 9))
    if hi < lo:
        lo, hi = hi, lo
    time.sleep(random.uniform(lo, hi))


def random_scroll_pause() -> None:
    time.sleep(random.uniform(0.4, 1.6))


def parse_employee_band(text: str) -> int | None:
    """
    Map '11-50', '1-10', '10001+', '50+' to a representative int for scoring.
    """
    if not text or not str(text).strip():
        return None
    t = str(text).lower().replace(",", "")
    m = re.search(r"(\d+)\s*[-–to]+\s*(\d+)", t, re.I)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    m = re.search(r"(\d+)\s*\+", t)
    if m:
        return int(m.group(1)) + 25
    m = re.search(r"(\d{1,6})", t)
    if m:
        return int(m.group(1))
    return None


def parse_revenue_millions(text: str) -> float | None:
    if not text:
        return None
    t = str(text).lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kmb])?\s*(?:usd|dollar)?", t, re.I)
    if not m:
        return None
    n = float(m.group(1))
    suf = (m.group(2) or "").lower()
    if suf == "k":
        n /= 1_000_000
    elif suf == "m":
        pass
    elif suf == "b":
        n *= 1_000
    return n


def with_retries(
    attempts: int = 3,
    base_delay: float = 1.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def inner(*a: Any, **kw: Any) -> T:
            last: Exception | None = None
            for i in range(attempts):
                try:
                    return fn(*a, **kw)
                except Exception as e:
                    last = e
                    if i < attempts - 1:
                        time.sleep(base_delay * (2**i) + random.uniform(0, 0.5))
            assert last is not None
            raise last

        return inner  # type: ignore[return-value]

    return deco
