"""
Apollo.io + Skrapp.io enrichment.

Requires API keys in environment:
  APOLLO_API_KEY   — https://apollo.io/api
  SKRAPP_API_KEY   — https://skrapp.io (exact header/name per your dashboard)

Flow: try Apollo person/org match first; if no verified email, try Skrapp.
Company-level fields are cached in-process to limit duplicate org calls.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from leadpilot.utils import get_logger, with_retries

log = get_logger("leadpilot.enrichment")

@dataclass
class EnrichmentResult:
    work_email: str = ""
    company_domain: str = ""
    industry: str = ""
    revenue: str = ""
    employee_count: str = ""
    status: str = "failed"  # enriched | partial | failed | skipped_config
    source: str = ""  # apollo | skrapp | cache | none
    raw_note: str = ""


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


@with_retries(attempts=3, base_delay=1.2)
def _apollo_people_match(
    *,
    linkedin_url: str,
    first_name: str,
    last_name: str,
    organization_name: str,
) -> dict[str, Any] | None:
    key = _env("APOLLO_API_KEY")
    if not key:
        return None
    try:
        import httpx
    except ImportError:
        log.warning("httpx not installed; skip Apollo")
        return None

    base = _env("APOLLO_BASE_URL", "https://api.apollo.io").rstrip("/")
    # Public documented shape (verify against your Apollo plan)
    url = f"{base}/v1/people/match"
    body: dict = {
        "api_key": key,
        "linkedin_url": linkedin_url or None,
    }
    if first_name or last_name:
        body["first_name"] = first_name or None
        body["last_name"] = last_name or None
    if organization_name:
        body["organization_name"] = organization_name
    h = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }
    if _env("APOLLO_USE_HEADER_KEY") == "1":
        h["X-Api-Key"] = key
        body.pop("api_key", None)

    with httpx.Client(timeout=45.0) as c:
        r = c.post(url, json=body, headers=h)

    if r.status_code == 401:
        log.error("Apollo 401: check APOLLO_API_KEY")
        return None
    if r.status_code == 429:
        log.warning("Apollo rate limit (429) — back off in production")
    if not r.is_success:
        log.debug("Apollo HTTP %s: %s", r.status_code, r.text[:300])
        return None
    data = r.json() if r.text else {}
    if isinstance(data, dict) and data.get("error"):
        log.debug("Apollo error field: %s", data.get("error"))
    return data if isinstance(data, dict) else None


@with_retries(attempts=3, base_delay=1.0)
def _skrapp_email(
    *,
    linkedin_url: str,
    first: str,
    last: str,
    company: str,
) -> str | None:
    key = _env("SKRAPP_API_KEY")
    if not key:
        return None
    try:
        import httpx
    except ImportError:
        return None

    base = _env("SKRAPP_BASE_URL", "https://api.skrapp.io").rstrip("/")
    # Skrapp endpoints differ by plan; common v2 find pattern:
    url = f"{base}/v2/find"
    params: dict = {}
    if linkedin_url:
        params["linkedinUrl"] = linkedin_url
    if first:
        params["firstName"] = first
    if last:
        params["lastName"] = last
    if company:
        params["company"] = company
    h = {
        "Accept": "application/json",
    }
    token_key = _env("SKRAPP_TOKEN_HEADER", "X-Access-Key")
    h[token_key] = key

    with httpx.Client(timeout=40.0) as c:
        r = c.get(url, params=params, headers=h)
    if not r.is_success:
        log.debug("Skrapp HTTP %s: %s", r.status_code, r.text[:200])
        return None
    j = r.json() if r.text else {}
    if not isinstance(j, dict):
        return None
    for k in (
        "email",
        "workEmail",
        "emails",
        "result",
    ):
        v = j.get(k)
        if isinstance(v, str) and "@" in v:
            return v
        if isinstance(v, list) and v and isinstance(v[0], str) and "@" in v[0]:
            return v[0]
    return None


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _extract_from_apollo_blob(blob: dict[str, Any] | None) -> EnrichmentResult:
    out = EnrichmentResult(status="partial", source="apollo")
    if not blob:
        return EnrichmentResult(status="failed", source="apollo")

    person: dict = (
        (blob.get("person") or blob) if isinstance(blob, dict) else {}
    )  # shape varies
    if not isinstance(person, dict):
        return EnrichmentResult(status="failed", source="apollo")

    email = (person.get("email") or person.get("sanitized_email") or "").strip()
    if "@" in email:
        out.work_email = email
        out.status = "enriched" if out.work_email else out.status

    org = person.get("organization")
    if isinstance(org, str):
        pass
    elif isinstance(org, dict):
        out.company_domain = (
            (org.get("primary_domain") or org.get("domain") or "")
        ).strip()
        out.revenue = str(
            (org.get("organization_revenue") or org.get("estimated_annual_revenue") or org.get("revenue_range") or "")
        )
        out.industry = (org.get("industry") or org.get("industries", [""])[0] or "").split(",")[0].strip()  # type: ignore[union-attr]  # noqa: E501
        ec = org.get("estimated_num_employees")
        if ec is not None:
            out.employee_count = str(ec)
    return out


def enrich_lead_row(
    row: dict[str, Any],
) -> EnrichmentResult:
    """
    Single lead: use Name, Company, Profile Link from LinkedIn scrape.
    Respects ENRICHMENT_ENABLED=0 to fast-skip.
    """
    if _env("ENRICHMENT_ENABLED", "1") == "0":
        return EnrichmentResult(
            status="skipped_config", source="none", raw_note="ENRICHMENT_ENABLED=0"
        )

    name = (row.get("Name") or "").strip()
    company = (row.get("Company") or "").strip()
    li_url = (row.get("Profile Link") or row.get("linkedin_url") or "").strip()
    first, last = _split_name(name)

    ap = _apollo_people_match(
        linkedin_url=li_url,
        first_name=first,
        last_name=last,
        organization_name=company,
    )
    res = _extract_from_apollo_blob(ap)

    if (not res.work_email or "@" not in res.work_email) and _env(
        "SKRAPP_API_KEY"
    ):
        em = _skrapp_email(
            linkedin_url=li_url, first=first, last=last, company=company
        )
        if em:
            res.work_email = em
            res.status = "enriched"
            if not res.source:
                res.source = "skrapp"
            res.raw_note = (res.raw_note + " +skrapp") if res.raw_note else "skrapp"
    if res.status == "partial" and (res.industry or res.company_domain or res.employee_count):
        res.status = "partial"
    if res.status == "partial" and not res.work_email and not res.industry:
        res.status = "failed" if not ap else "partial"
    if not ap and not _env("APOLLO_API_KEY"):
        res = EnrichmentResult(
            status="skipped_config", source="none", raw_note="set APOLLO_API_KEY and/or SKRAPP_API_KEY"
        )
    return res


def enrich_batch(rows: list[dict[str, Any]]) -> list[tuple[dict, EnrichmentResult]]:
    out: list[tuple[dict, EnrichmentResult]] = []
    for r in rows:
        try:
            e = enrich_lead_row(r)
        except Exception as ex:
            log.exception("enrich error: %s", ex)
            e = EnrichmentResult(status="failed", raw_note=str(ex)[:200])
        out.append((r, e))
    return out


def merge_enrichment(row: dict, e: EnrichmentResult) -> dict:
    m = {**row}
    m["work_email"] = e.work_email
    m["company_domain"] = e.company_domain
    m["industry"] = e.industry
    m["revenue"] = e.revenue
    m["employee_count"] = e.employee_count
    m["enrichment_status"] = e.status
    m["enrichment_source"] = e.source
    m["enrichment_note"] = e.raw_note
    return m
