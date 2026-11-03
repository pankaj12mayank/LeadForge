from __future__ import annotations

import re
from typing import Any

from app.services.llm import LLMError, call_json
from app.schemas.lead_plan import LeadPlan

PRO_SOURCE_NAMES = {"places"}


def _rule_based(query: str) -> LeadPlan:
    q = query.lower()
    sources = ["apollo", "websearch"]
    locations = re.findall(r"\b(in|at|near|for)\s+([a-zA-Z\s]+?)(?:\b(?:jinke|who|that|with)|$)", q)
    location = locations[0][1].strip() if locations else ""
    keywords = [w for w in re.split(r"[,\s]+", q) if len(w) > 3]
    return LeadPlan(
        sources=sources,
        filters={"keywords": keywords[:8], "locations": [location] if location else []},
        target_count=10,
        notes="rule-based fallback",
    )


async def plan_query(query: str, *, features: dict | None = None) -> LeadPlan:
    features = features or {}
    allowed = set(features.get("sources", ["apollo", "websearch"]))
    system = (
        "You are a lead-sourcing planner. Convert the user's natural-language query into a strict JSON plan. "
        'Keys: sources (list of "apollo"|"websearch"|"places"), filters {titles, locations, employee_range, keywords, industries}, '
        "target_count (1-500), notes. Output ONLY JSON."
    )
    try:
        result = await call_json(system, query, LeadPlan)
        plan = result.obj
    except (LLMError, Exception):
        plan = None
    if plan is None:
        plan = _rule_based(query)

    # Drop pro-only sources for non-pro plans.
    plan.sources = [s for s in plan.sources if s in allowed or s not in PRO_SOURCE_NAMES]
    if not plan.sources:
        plan.sources = ["websearch"] if "websearch" in allowed else ["apollo"]
    return plan
