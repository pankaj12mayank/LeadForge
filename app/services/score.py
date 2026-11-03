from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.llm import call_json


class LeadScore(BaseModel):
    score: int = Field(ge=0, le=100)
    tier: str = Field(pattern="^(hot|warm|cold)$")
    pain_point: str | None = None
    reason: str
    opener: str | None = None


LEADERSHIP_KEYWORDS = {"founder", "ceo", "cto", "director", "head", "owner", "partner", "vp", "president"}


def _rule_score(lead: dict, is_pro: bool) -> dict:
    name = str(lead.get("name") or "")
    title = str(lead.get("title") or "")
    company = str(lead.get("company") or "")
    email = bool(lead.get("email"))
    linkedin = bool(lead.get("linkedin_url"))
    text = f"{name} {title} {company}".lower()
    score = 0
    if email:
        score += 30
    if linkedin:
        score += 20
    if any(k in text for k in LEADERSHIP_KEYWORDS):
        score += 30
    if title:
        score += 10
    if company:
        score += 10
    score = min(score, 100)
    tier = "hot" if score >= 80 else ("warm" if score >= 50 else "cold")
    reason = f"Score {score}: {'email found; ' if email else ''}{'LinkedIn profile; ' if linkedin else ''}{'senior title' if any(k in text for k in LEADERSHIP_KEYWORDS) else ''}".strip()
    opener = (
        f"Hi {name.split(' ')[0] if name else 'there'}, I saw {company} and thought..."
        if (is_pro and name and company)
        else None
    )
    return {"score": score, "tier": tier, "pain_point": None, "reason": reason or "rule-based score", "opener": opener}


async def score_leads(leads: list[dict[str, Any]], *, is_pro: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    from app.config import settings

    if settings.LLM_PROVIDER == "none":
        for lead in leads:
            merged = dict(lead)
            merged.update(_rule_score(lead, is_pro))
            out.append(merged)
        return out

    system = (
        "Score a sales lead 0-100. Return JSON: {score:int 0-100, tier:'hot'|'warm'|'cold', "
        "pain_point:string|null, reason:string, opener:string|null}. "
        "Higher for decision-makers with email/LinkedIn. Output ONLY JSON."
    )
    n_strong = max(1, int(len(leads) * 0.2)) if is_pro else 0
    for i, lead in enumerate(leads):
        merged = dict(lead)
        try:
            user = f"Lead: {lead}"
            result = await call_json(system, user, LeadScore)
            obj = result.obj or LeadScore(score=50, tier="warm", pain_point=None, reason="llm score", opener=None)
            if not is_pro:
                obj.opener = None
            merged.update(obj.model_dump())
        except Exception as exc:  # noqa: BLE001
            merged.update(_rule_score(lead, is_pro))
            merged["reason"] = f"llm fallback: {exc}"
        out.append(merged)
    return out
