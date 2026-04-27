"""
Lead scoring: weighted rules (0–100) + optional GPT for refinement and narrative.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from leadpilot.utils import env_bool, get_logger, parse_employee_band

log = get_logger("leadpilot.scoring")

_DECISION_RE = re.compile(
    r"\b(ceo|cto|cfo|coo|founder|co-founder|owner|president|vp|vice president|"
    r"head|director|chief|partner|managing|lead|principal)\b",
    re.I,
)
_ICP_LO = 10
_ICP_HI = 200


@dataclass
class ScoreResult:
    score: int
    priority: str  # Hot | Warm | Cold
    reasoning: str
    problems_refined: str


def _role_points(role: str) -> int:
    r = (role or "").strip()
    if not r:
        return 5
    if _DECISION_RE.search(r):
        return 30
    if re.search(r"\b(manager|senior|lead)\b", r, re.I):
        return 18
    return 10


def _size_points(team_text: str, employees_enriched: str) -> int:
    raw = employees_enriched or team_text
    n = parse_employee_band(str(raw)) if raw else None
    if n is None:
        return 8
    if _ICP_LO <= n <= _ICP_HI:
        return 20
    if 5 <= n < _ICP_LO or _ICP_HI < n <= 500:
        return 12
    return 6


def _problem_intensity(problems: str) -> int:
    p = (problems or "").lower()
    if not p or p in ("—", "-", "n/a"):
        return 5
    score = 10
    for kw in ("automation", "scale", "growth", "hiring", "cost", "efficiency", "compliance", "security"):
        if kw in p:
            score += 2
    return min(25, score + min(len(p) // 80, 5))


def _digital_gap(overview: str) -> int:
    o = (overview or "").lower()
    if len(o) < 40:
        return 5
    gap = 0
    if "digital" not in o and "online" not in o and "software" not in o:
        gap += 8
    if "legacy" in o or "manual" in o or "paper" in o:
        gap += 7
    return min(15, gap or 4)


def _activity_points(last_active: str) -> int:
    # We rarely have real last-active; reward presence of a non-default value
    la = (last_active or "").strip()
    if not la or la.upper() == "N/A":
        return 3
    if re.search(r"hour|day|week|active", la, re.I):
        return 10
    return 5


def score_rule_based(row: dict[str, Any]) -> ScoreResult:
    role = str(row.get("Role") or "")
    team = str(row.get("Team Size") or row.get("team_size_linkedin") or "")
    empc = str(row.get("employee_count") or row.get("Employee Count") or "")
    prob = str(row.get("Problem Seen") or row.get("problems") or "")
    overview = str(
        row.get("company_overview")
        or row.get("Company Overview")
        or row.get("Solution")
        or ""
    )
    last = str(row.get("Last Active") or "N/A")

    p1 = _role_points(role)
    p2 = _size_points(team, empc)
    p3 = _problem_intensity(prob)
    p4 = _digital_gap(overview)
    p5 = _activity_points(last)
    total = p1 + p2 + p3 + p4 + p5
    total = min(100, max(0, int(total)))

    if total >= 72:
        pr = "Hot"
    elif total >= 45:
        pr = "Warm"
    else:
        pr = "Cold"
    reason = (
        f"role={p1} size={p2} problem={p3} digital_gap={p4} activity={p5} (weighted model)"
    )
    return ScoreResult(
        score=total,
        priority=pr,
        reasoning=reason,
        problems_refined=prob,
    )


def _gpt_refine(problems: str, row: dict[str, Any]) -> str | None:
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        return None
    if not env_bool("SCORING_USE_GPT", False):
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=(os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip(),
    )
    text = f"Role: {row.get('Role')}\nCompany: {row.get('Company')}\nProblems: {problems}\nOverview hint: {row.get('Team Size', '')} {row.get('industry', '')}"
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Refine the 'problems' into 2-4 short bullet phrases for B2B sales. English only. No filler.",
                },
                {"role": "user", "content": text[:8000]},
            ],
            max_tokens=300,
        )
        return (r.choices[0].message.content or "").strip() or None
    except Exception as e:
        log.debug("GPT refine err: %s", e)
        return None


def _gpt_score(row: dict[str, Any], base: ScoreResult) -> ScoreResult | None:
    if not env_bool("SCORING_GPT_SCORE", False):
        return None
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=(os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip(),
    )
    lead_bits = " | ".join(
        f"{k}={row.get(k)}"
        for k in ("Name", "Role", "Company", "industry", "Team Size", "Problem Seen")
    )
    msg = f"""Given this lead, output a single line: SCORE=0-100|PRIORITY=Hot|Warm|Cold|REASON=short
Lead: {lead_bits}
Rule baseline was {base.score} ({base.priority}).
"""
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": msg[:12000]}],
            max_tokens=200,
        )
        line = (r.choices[0].message.content or "").strip()
        m = re.search(r"SCORE=(\d+)", line, re.I)
        m2 = re.search(r"PRIORITY=(Hot|Warm|Cold)", line, re.I)
        m3 = re.search(r"REASON=(.+)", line, re.I)
        if m:
            sc = min(100, max(0, int(m.group(1))))
            pr = m2.group(1) if m2 else base.priority
            reas = m3.group(1).strip() if m3 else line[:200]
            return ScoreResult(score=sc, priority=pr, reasoning=reas, problems_refined=base.problems_refined)
    except Exception as e:
        log.debug("GPT score err: %s", e)
    return None


def apply_scoring(row: dict[str, Any]) -> dict[str, Any]:
    s = score_rule_based(row)
    pr = s.problems_refined
    g1 = _gpt_refine(pr, row)
    if g1:
        s = ScoreResult(
            score=s.score, priority=s.priority, reasoning=s.reasoning, problems_refined=g1
        )
    g2 = _gpt_score(row, s)
    if g2:
        s = g2
    out = {**row}
    out["lead_score"] = s.score
    out["priority"] = s.priority
    out["scoring_reasoning"] = s.reasoning
    out["problems_refined"] = s.problems_refined
    return out
