from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import current_user, current_org_id, require_user
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import CreditLedger, Job, JobStatus, Organization, Search, Subscription
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
    plan = None
    if sub:
        from app.models import Plan

        plan = db.get(Plan, sub.plan_id)
    recent_jobs = (
        db.query(Job)
        .filter(Job.org_id == org_id)
        .order_by(Job.created_at.desc())
        .limit(10)
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
        org=org,
        credits=credits,
        sub=sub,
        plan=plan,
        jobs=recent_jobs,
        searches=recent_searches,
        settings=settings,
        user=user,
    )
