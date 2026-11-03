from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Lead


def _norm(v: str | None) -> str | None:
    if v is None:
        return None
    v = str(v).strip().lower()
    return v or None


def _key(lead: dict) -> tuple[str, ...] | None:
    email = _norm(lead.get("email"))
    linkedin = _norm(lead.get("linkedin_url"))
    domain = _norm(lead.get("domain"))
    name = _norm(lead.get("name"))
    if email:
        return ("email", email)
    if linkedin:
        return ("linkedin", linkedin)
    if domain and name:
        return ("domain_name", domain, name)
    return None


def merge_incoming(leads: list[dict]) -> list[dict]:
    """Deduplicate within a single job batch."""
    seen: set[tuple[str, ...]] = set()
    out: list[dict] = []
    for lead in leads:
        k = _key(lead)
        if k is None or k in seen:
            continue
        seen.add(k)
        out.append(lead)
    return out


def merge_against_org(leads: list[dict], org_id: int, db: Session) -> list[dict]:
    """Remove leads that already exist in the org (by unique keys)."""
    existing = db.query(Lead).filter(Lead.org_id == org_id).all()
    seen: set[tuple[str, ...]] = set()
    for l in existing:
        if l.email:
            seen.add(("email", l.email.lower()))
        if l.linkedin_url:
            seen.add(("linkedin", l.linkedin_url.lower()))
        if l.domain and l.name:
            seen.add(("domain_name", l.domain.lower(), l.name.lower()))
    out: list[dict] = []
    for lead in leads:
        k = _key(lead)
        if k is None or k in seen:
            continue
        seen.add(k)
        out.append(lead)
    return out
