from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.sources.base import RawLead

log = logging.getLogger("leadforge.services.enrich")


def _norm_email(v: Any) -> str | None:
    if not v:
        return None
    v = str(v).strip()
    return v or None


async def _apollo_email(api_key: str, domain: str) -> str | None:
    if not domain:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.apollo.io/v1/people/match",
                params={"api_key": api_key, "domain": domain},
            )
        if resp.status_code != 200:
            return None
        data = resp.json() or {}
        return _norm_email(data.get("email"))
    except Exception as exc:  # noqa: BLE001
        log.debug("apollo enrich failed: %s", exc)
        return None


async def _hunter_email(api_key: str, domain: str) -> str | None:
    if not domain:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": api_key},
            )
        if resp.status_code != 200:
            return None
        data = resp.json() or {}
        emails = (data.get("data") or {}).get("emails") or []
        if emails:
            return _norm_email(emails[0].get("value"))
        return None
    except Exception as exc:  # noqa: BLE001
        log.debug("hunter enrich failed: %s", exc)
        return None


async def _skrapp_email(api_key: str, domain: str) -> str | None:
    # Skrapp has no public simple endpoint; keep as graceful stub.
    return None


async def enrich_lead(lead: RawLead, keys: dict[str, str | None]) -> RawLead:
    """Waterfall: Apollo -> Hunter -> Skrapp. Stop at first hit."""
    lead = dict(lead)
    domain = lead.get("domain")
    if lead.get("email"):
        lead["email_status"] = lead.get("email_status") or "found"
        return lead
    email = await _apollo_email(keys.get("apollo") or "", domain or "")
    if email:
        lead["email"] = email
        lead["email_status"] = "found"
        lead["enrichment_source"] = "apollo"
        return lead
    email = await _hunter_email(keys.get("hunter") or "", domain or "")
    if email:
        lead["email"] = email
        lead["email_status"] = "found"
        lead["enrichment_source"] = "hunter"
        return lead
    email = await _skrapp_email(keys.get("skrapp") or "", domain or "")
    if email:
        lead["email"] = email
        lead["email_status"] = "found"
        lead["enrichment_source"] = "skrapp"
        return lead
    lead["email_status"] = lead.get("email_status") or "not_found"
    return lead


async def enrich_batch(leads: list[RawLead], keys: dict[str, str | None]) -> list[RawLead]:
    import asyncio

    return await asyncio.gather(*(enrich_lead(l, keys) for l in leads))
