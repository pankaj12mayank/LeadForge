from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.deps import current_org_id, require_user
from app.config import settings
from app.db import get_db
from app.models import CreditLedger, Job, JobStatus, Lead, Organization, Plan, Search, Subscription
from app.services.quota import get_credits

router = APIRouter()


def _render(request: Request, template: str, status_code: int = 200, user=None, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", user)
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


@router.get("/dashboard")
def dashboard(request: Request, user=Depends(require_user), org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    credits = get_credits(org_id, db)
    sub = (
        db.query(Subscription)
        .filter(Subscription.org_id == org_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    plan = db.get(Plan, sub.plan_id) if sub else None

    # Real queries & aggregates
    total_leads = db.query(Lead).filter(Lead.org_id == org_id).count()
    active_jobs_count = (
        db.query(Job)
        .filter(Job.org_id == org_id, Job.status.in_([JobStatus.running, JobStatus.queued]))
        .count()
    )
    avg_score_res = (
        db.query(func.avg(Lead.score))
        .filter(Lead.org_id == org_id, Lead.score.isnot(None))
        .scalar()
    )
    avg_score = round(float(avg_score_res), 1) if avg_score_res is not None else 0

    # 3D Bar chart aggregates: Leads delivered in past 6 weeks
    now = datetime.now(timezone.utc)
    weekly_bars = []
    has_bar_data = False
    for i in range(5, -1, -1):
        start = now - timedelta(days=(i + 1) * 7)
        end = now - timedelta(days=i * 7)
        cnt = db.query(Lead).filter(Lead.org_id == org_id, Lead.created_at >= start, Lead.created_at < end).count()
        if cnt > 0:
            has_bar_data = True
        lbl = f"W{6 - i}"
        h = min(140, max(16, cnt * 10)) if cnt > 0 else 12
        weekly_bars.append({
            "h": h,
            "tip": f"{lbl}: {cnt} leads",
            "label": lbl,
            "c": "var(--acc)",
            "delay": round((5 - i) * 0.1, 2),
        })
    if not has_bar_data and total_leads == 0:
        weekly_bars = []

    # Credits line chart data
    credits_usage = (
        db.query(CreditLedger)
        .filter(CreditLedger.org_id == org_id, CreditLedger.delta < 0)
        .order_by(CreditLedger.created_at.asc())
        .limit(10)
        .all()
    )
    line_data = None
    if credits_usage:
        pts = []
        x_coords = [60, 140, 220, 300, 380, 460, 520]
        step = max(1, len(credits_usage) // len(x_coords) or 1)
        sub_pts = credits_usage[::step][:len(x_coords)]
        max_val = max(abs(e.delta) for e in credits_usage) or 10
        for idx, entry in enumerate(sub_pts):
            cx = x_coords[idx] if idx < len(x_coords) else 500
            used = abs(entry.delta)
            cy = int(200 - (used / max_val * 140))
            pts.append({
                "x": cx,
                "y": cy,
                "w": f"#{idx+1}",
                "t": f"{used} credits used"
            })
        if pts:
            line_d = "M " + " L ".join(f"{p['x']},{p['y']}" for p in pts)
            area_d = f"M 40,210 L {pts[0]['x']},{pts[0]['y']} " + " ".join(f"L {p['x']},{p['y']}" for p in pts) + f" L {pts[-1]['x']},210 Z"
            line_data = {
                "points": pts,
                "line_d": line_d,
                "area_d": area_d,
                "grid": [
                    {"y": 60, "ty": 64, "l": f"{max_val}"},
                    {"y": 130, "ty": 134, "l": f"{max_val // 2}"},
                    {"y": 200, "ty": 204, "l": "0"}
                ]
            }

    recent_jobs = (
        db.query(Job)
        .filter(Job.org_id == org_id)
        .order_by(Job.created_at.desc())
        .limit(8)
        .all()
    )
    recent_searches = (
        db.query(Search)
        .filter(Search.org_id == org_id)
        .order_by(Search.created_at.desc())
        .limit(5)
        .all()
    )
    return _render(
        request,
        "dashboard.html",
        active_page="dashboard",
        page_title="Dashboard",
        page_sub="Real-time lead sourcing pipeline and credit balance",
        org=org,
        credits=credits,
        sub=sub,
        plan=plan,
        total_leads=total_leads,
        active_jobs_count=active_jobs_count,
        avg_score=avg_score,
        weekly_bars=weekly_bars,
        line_data=line_data,
        jobs=recent_jobs,
        searches=recent_searches,
        settings=settings,
        user=user,
    )
