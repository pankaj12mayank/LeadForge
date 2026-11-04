from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.auth.deps import require_admin
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import (
    ApiKey, AuditLog, CreditLedger, Job, JobStatus, Lead, Organization,
    Plan, Search, Subscription, SubStatus, User, WebhookEvent,
)
from app.services.quota import add_credits, get_credits

router = APIRouter()


def _render(request: Request, template: str, status_code: int = 200, user=None, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", user)
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


def _audit(db: Session, actor_id: int | None, action: str, target: str | None = None, meta: dict | None = None):
    db.add(AuditLog(actor_id=actor_id, action=action, target=target, meta=meta or {}))


# ── Overview ──────────────────────────────────────────────────────────────

@router.get("/admin")
def admin_overview(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    users = db.query(User).count()
    orgs = db.query(Organization).count()
    jobs_today = db.query(Job).filter(Job.created_at >= now - timedelta(days=1)).count()
    jobs_failed = db.query(Job).filter(Job.status == JobStatus.failed).count()
    jobs_done = db.query(Job).filter(Job.status == JobStatus.done).count()
    total_jobs = db.query(Job).count()
    failure_rate = round((jobs_failed / total_jobs * 100) if total_jobs else 0, 1)

    # MRR from active subscriptions
    active_subs = (
        db.query(Subscription, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .filter(Subscription.status == SubStatus.active)
        .all()
    )
    mrr = sum(p.price_inr for _, p in active_subs)

    return _render(
        request,
        "admin/overview.html",
        active_page="overview",
        users=users,
        orgs=orgs,
        mrr=mrr,
        jobs_today=jobs_today,
        failure_rate=failure_rate,
        jobs_done=jobs_done,
        settings=settings,
        user=user,
    )


# ── Users / Orgs ──────────────────────────────────────────────────────────

@router.get("/admin/users")
def admin_users(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .all()
    )
    orgs = db.query(Organization).all()
    plans = db.query(Plan).all()
    org_credits = {}
    org_plan = {}
    for o in orgs:
        sub = (
            db.query(Subscription)
            .filter(Subscription.org_id == o.id)
            .order_by(Subscription.created_at.desc())
            .first()
        )
        plan = db.get(Plan, sub.plan_id) if sub else None
        org_credits[o.id] = get_credits(o.id, db)
        org_plan[o.id] = plan.name if plan else "trial"
    return _render(
        request,
        "admin/users.html",
        active_page="users",
        users=users,
        orgs=orgs,
        plans=plans,
        org_credits=org_credits,
        org_plan=org_plan,
        settings=settings,
        user=user,
        db=db,
    )


@router.post("/admin/users/{uid}/toggle")
def admin_toggle_user(
    request: Request,
    uid: int,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, uid)
    if not u:
        return HTMLResponse("Not found", status_code=404)
    u.is_active = not u.is_active
    _audit(db, user.id, "toggle_user", str(uid), {"is_active": u.is_active})
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"User updated"}}'})


@router.post("/admin/orgs/{oid}/toggle")
def admin_toggle_org(
    request: Request,
    oid: int,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    o = db.get(Organization, oid)
    if not o:
        return HTMLResponse("Not found", status_code=404)
    # Deactivate all users in org
    for m in o.memberships:
        m.user.is_active = not m.user.is_active
    _audit(db, user.id, "toggle_org", str(oid), {})
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Org updated"}}'})


@router.post("/admin/orgs/{oid}/credits")
def admin_grant_credits(
    request: Request,
    oid: int,
    amount: int = Form(...),
    reason: str = Form("manual grant"),
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    add_credits(oid, amount, reason, db)
    _audit(db, user.id, "grant_credits", str(oid), {"amount": amount, "reason": reason})
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Credits granted"}}'})


@router.post("/admin/orgs/{oid}/plan")
def admin_change_plan(
    request: Request,
    oid: int,
    plan_code: str = Form(...),
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    sub = (
        db.query(Subscription)
        .filter(Subscription.org_id == oid)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    plan = db.query(Plan).filter(Plan.code == plan_code).first()
    if not sub or not plan:
        return HTMLResponse("Not found", status_code=404)
    sub.plan_id = plan.id
    _audit(db, user.id, "change_plan", str(oid), {"plan": plan_code})
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Plan changed"}}'})


# ── Jobs ──────────────────────────────────────────────────────────────────

@router.get("/admin/jobs")
def admin_jobs(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(100).all()
    return _render(
        request,
        "admin/jobs.html",
        active_page="jobs",
        jobs=jobs,
        settings=settings,
        user=user,
    )


@router.post("/admin/jobs/{jid}/retry")
def admin_retry_job(
    request: Request,
    jid: int,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    j = db.get(Job, jid)
    if not j:
        return HTMLResponse("Not found", status_code=404)
    j.status = JobStatus.queued
    j.locked_at = None
    j.run_after = datetime.now(timezone.utc)
    j.error = None
    _audit(db, user.id, "retry_job", str(jid), {})
    db.commit()
    return RedirectResponse(url="/admin/jobs", status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Job retried"}}'})


@router.post("/admin/jobs/{jid}/cancel")
def admin_cancel_job(
    request: Request,
    jid: int,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    j = db.get(Job, jid)
    if not j:
        return HTMLResponse("Not found", status_code=404)
    j.status = JobStatus.failed
    j.error = "cancelled by admin"
    _audit(db, user.id, "cancel_job", str(jid), {})
    db.commit()
    return RedirectResponse(url="/admin/jobs", status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Job cancelled"}}'})


# ── Plans ─────────────────────────────────────────────────────────────────

@router.get("/admin/plans")
def admin_plans(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    plans = db.query(Plan).order_by(Plan.price_inr).all()
    return _render(
        request,
        "admin/plans.html",
        active_page="plans",
        plans=plans,
        settings=settings,
        user=user,
    )


@router.post("/admin/plans/{pid}/edit")
def admin_edit_plan(
    request: Request,
    pid: int,
    price_inr: int = Form(...),
    monthly_credits: int = Form(...),
    seats: int = Form(...),
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    plan = db.get(Plan, pid)
    if not plan:
        return HTMLResponse("Not found", status_code=404)
    plan.price_inr = price_inr
    plan.monthly_credits = monthly_credits
    plan.seats = seats
    _audit(db, user.id, "edit_plan", str(pid), {"price": price_inr, "credits": monthly_credits, "seats": seats})
    db.commit()
    return RedirectResponse(url="/admin/plans", status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Plan updated"}}'})


# ── Provider health ───────────────────────────────────────────────────────

@router.get("/admin/providers")
def admin_providers(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    providers = [
        {"name": "Apollo", "ok": bool(settings.APOLLO_API_KEY)},
        {"name": "Hunter", "ok": bool(settings.HUNTER_API_KEY)},
        {"name": "Skrapp", "ok": bool(settings.SKRAPP_API_KEY)},
        {"name": "Tavily/Serper", "ok": bool(settings.TAVILY_API_KEY or settings.SERPER_API_KEY)},
        {"name": "Google Places", "ok": bool(settings.GOOGLE_PLACES_API_KEY)},
        {"name": "OpenAI/Ollama", "ok": settings.LLM_PROVIDER != "none"},
        {"name": "Razorpay", "ok": bool(settings.RAZORPAY_KEY_ID)},
        {"name": "LeadOps", "ok": bool(settings.LEADOPS_URL)},
    ]
    return _render(
        request,
        "admin/providers.html",
        active_page="providers",
        providers=providers,
        settings=settings,
        user=user,
    )


# ── Audit log ─────────────────────────────────────────────────────────────

@router.get("/admin/audit")
def admin_audit(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return _render(
        request,
        "admin/audit.html",
        active_page="audit",
        logs=logs,
        settings=settings,
        user=user,
    )
