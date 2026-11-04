from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.auth.deps import require_admin
from app.config import settings
from app.db import get_db
from app.models import (
    AuditLog, Job, JobStatus, Membership, Organization,
    Plan, Subscription, SubStatus, User,
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
    jobs_running = db.query(Job).filter(Job.status == JobStatus.running).count()
    jobs_queued = db.query(Job).filter(Job.status == JobStatus.queued).count()
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

    # 3D Donut segments for jobs by status
    donut_legend = []
    if total_jobs > 0:
        pct_done = round(jobs_done / total_jobs * 100)
        pct_run = round(jobs_running / total_jobs * 100)
        pct_fail = round(jobs_failed / total_jobs * 100)
        pct_queue = max(0, 100 - pct_done - pct_run - pct_fail)
        
        offset = 0
        donut_legend = [
            {"label": "Done", "value": jobs_done, "color": "var(--ok)", "pct": pct_done, "offset": offset},
            {"label": "Running", "value": jobs_running, "color": "var(--acc2)", "pct": pct_run, "offset": offset + pct_done},
            {"label": "Failed", "value": jobs_failed, "color": "var(--bad)", "pct": pct_fail, "offset": offset + pct_done + pct_run},
            {"label": "Queued", "value": jobs_queued, "color": "var(--warn)", "pct": pct_queue, "offset": offset + pct_done + pct_run + pct_fail},
        ]
    elif jobs_done or jobs_queued:
        donut_legend = [{"label": "Queued", "value": jobs_queued or 1, "color": "var(--warn)", "pct": 100, "offset": 0}]

    # 3D Bar chart: New signups per month (past 6 months)
    signups_bars = []
    for i in range(5, -1, -1):
        m_start = now - timedelta(days=(i + 1) * 30)
        m_end = now - timedelta(days=i * 30)
        u_count = db.query(User).filter(User.created_at >= m_start, User.created_at < m_end).count()
        lbl = (now - timedelta(days=i * 30)).strftime('%b')
        h = min(140, max(16, u_count * 20)) if u_count > 0 else 14
        signups_bars.append({
            "h": h,
            "tip": f"{lbl}: {u_count} signups",
            "label": lbl,
            "c": "var(--acc)",
            "delay": round((5 - i) * 0.1, 2),
        })

    # MRR Line chart data
    mrr_line = {
        "points": [
            {"x": 60, "y": 180, "w": "May", "t": f"₹{mrr // 4}"},
            {"x": 160, "y": 150, "w": "Jun", "t": f"₹{mrr // 3}"},
            {"x": 260, "y": 120, "w": "Jul", "t": f"₹{mrr // 2}"},
            {"x": 360, "y": 90, "w": "Aug", "t": f"₹{int(mrr * 0.75)}"},
            {"x": 460, "y": 60, "w": "Sep", "t": f"₹{mrr}"},
            {"x": 520, "y": 50, "w": "Oct", "t": f"₹{mrr}"},
        ],
        "line_d": "M 60,180 L 160,150 L 260,120 L 360,90 L 460,60 L 520,50",
        "area_d": "M 40,210 L 60,180 L 160,150 L 260,120 L 360,90 L 460,60 L 520,50 L 520,210 Z",
        "grid": [
            {"y": 50, "ty": 54, "l": f"₹{mrr or 1000}"},
            {"y": 120, "ty": 124, "l": f"₹{(mrr or 1000) // 2}"},
            {"y": 190, "ty": 194, "l": "₹0"}
        ]
    }

    # Needs attention list (failed jobs)
    needs_attention = (
        db.query(Job)
        .filter(Job.status == JobStatus.failed)
        .order_by(Job.created_at.desc())
        .limit(5)
        .all()
    )

    # 4 Stat cards with sparklines
    stats = [
        {
            "l": "Total MRR",
            "v": f"₹{mrr:,}" if mrr else "₹0",
            "pts": "2,26 18,22 34,24 50,14 66,16 82,6",
            "c": "var(--ok)",
            "n": "from active subscriptions",
        },
        {
            "l": "Active orgs",
            "v": str(orgs),
            "pts": "2,24 18,20 34,22 50,16 66,12 82,8",
            "c": "var(--acc)",
            "n": f"{users} registered users",
        },
        {
            "l": "Failure rate",
            "v": f"{failure_rate}%",
            "pts": "2,12 18,16 34,14 50,22 66,20 82,26",
            "c": "var(--bad)" if failure_rate > 10 else "var(--ok)",
            "n": f"{jobs_failed} failed of {total_jobs} total",
        },
        {
            "l": "Jobs today",
            "v": str(jobs_today),
            "pts": "2,26 18,22 34,18 50,20 66,12 82,8",
            "c": "var(--acc2)",
            "n": "runs executed past 24h",
        },
    ]

    return _render(
        request,
        "admin/overview.html",
        active_page="overview",
        page_title="Overview",
        page_sub="LeadForge system metrics, MRR, and platform health",
        users=users,
        orgs=orgs,
        mrr=mrr,
        jobs_today=jobs_today,
        failure_rate=failure_rate,
        jobs_done=jobs_done,
        jobs_running=jobs_running,
        jobs_queued=jobs_queued,
        stats=stats,
        donut_legend=donut_legend,
        signups_bars=signups_bars,
        mrr_line=mrr_line,
        needs_attention=needs_attention,
        settings=settings,
        user=user,
    )


# ── Users / Orgs ──────────────────────────────────────────────────────────

@router.get("/admin/users")
def admin_users(
    request: Request,
    user=Depends(require_admin),
    q: str | None = None,
    plan_filter: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    query = db.query(User).order_by(User.created_at.desc())
    if q:
        like = f"%{q}%"
        query = query.filter((User.name.ilike(like)) | (User.email.ilike(like)))

    if plan_filter and plan_filter != "all":
        matching_plan = db.query(Plan).filter(func.lower(Plan.name) == plan_filter.lower()).first()
        if matching_plan:
            matching_org_ids = [
                s.org_id for s in db.query(Subscription).filter(Subscription.plan_id == matching_plan.id).all()
            ]
            matching_user_ids = [
                m.user_id for m in db.query(Membership).filter(Membership.org_id.in_(matching_org_ids)).all()
            ]
            query = query.filter(User.id.in_(matching_user_ids))

    PAGE_SIZE = 6
    total_users = query.count()
    total_pages = max(1, (total_users + PAGE_SIZE - 1) // PAGE_SIZE) if total_users > 0 else 1
    page = max(1, min(page, total_pages))
    users = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

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

    start_idx = (page - 1) * PAGE_SIZE + 1 if total_users > 0 else 0
    end_idx = min(page * PAGE_SIZE, total_users)
    range_text = f"Showing {start_idx}-{end_idx} of {total_users} users"

    return _render(
        request,
        "admin/users.html",
        active_page="users",
        page_title="Users & Organizations",
        page_sub=f"{total_users} registered users across {len(orgs)} organizations",
        users=users,
        total_users=total_users,
        page=page,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        range_text=range_text,
        q=q or "",
        plan_filter=plan_filter or "all",
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
    target_url = request.headers.get("referer") or "/admin/users"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"User updated"}}'})


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
    target_url = request.headers.get("referer") or "/admin/users"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Org updated"}}'})


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
    target_url = request.headers.get("referer") or "/admin/users"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Credits granted"}}'})


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
    target_url = request.headers.get("referer") or "/admin/users"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Plan changed"}}'})


# ── Jobs ──────────────────────────────────────────────────────────────────

@router.get("/admin/jobs")
def admin_jobs(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(100).all()
    orgs = {o.id: o.name for o in db.query(Organization).all()}
    return _render(
        request,
        "admin/jobs.html",
        active_page="jobs",
        page_title="Jobs Monitor",
        page_sub=f"Monitoring background sourcing and enrichment jobs across {len(orgs)} organizations",
        jobs=jobs,
        orgs=orgs,
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
    target_url = request.headers.get("referer") or "/admin/jobs"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Job retried"}}'})


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
    target_url = request.headers.get("referer") or "/admin/jobs"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Job cancelled"}}'})


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
        page_title="Plans Editor",
        page_sub="Configure subscription pricing, monthly quotas, and team seats",
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
    target_url = request.headers.get("referer") or "/admin/plans"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": '{"toast":{"kind":"ok","title":"Plan updated"}}'})


# ── Provider health ───────────────────────────────────────────────────────

@router.get("/admin/providers")
def admin_providers(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    providers = [
        {"name": "Apollo", "kind": "Email & People Data", "env": "APOLLO_API_KEY", "ok": bool(settings.APOLLO_API_KEY)},
        {"name": "Hunter", "kind": "Email Verification", "env": "HUNTER_API_KEY", "ok": bool(settings.HUNTER_API_KEY)},
        {"name": "Skrapp", "kind": "B2B Email Finder", "env": "SKRAPP_API_KEY", "ok": bool(settings.SKRAPP_API_KEY)},
        {"name": "Tavily/Serper", "kind": "Web Search Engine", "env": "TAVILY_API_KEY / SERPER", "ok": bool(settings.TAVILY_API_KEY or settings.SERPER_API_KEY)},
        {"name": "Google Places", "kind": "Local Business Discovery", "env": "GOOGLE_PLACES_API_KEY", "ok": bool(settings.GOOGLE_PLACES_API_KEY)},
        {"name": "OpenAI/Ollama", "kind": "AI Scoring & LLM", "env": "LLM_PROVIDER", "ok": settings.LLM_PROVIDER != "none"},
        {"name": "Razorpay", "kind": "Billing & Subscriptions", "env": "RAZORPAY_KEY_ID", "ok": bool(settings.RAZORPAY_KEY_ID)},
        {"name": "LeadOps", "kind": "Orchestration Webhook", "env": "LEADOPS_URL", "ok": bool(settings.LEADOPS_URL)},
    ]
    return _render(
        request,
        "admin/providers.html",
        active_page="providers",
        page_title="Provider Health",
        page_sub="API keys and external service connectivity",
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
        page_title="Audit Log",
        page_sub="Chronological record of administrative operations and security events",
        logs=logs,
        settings=settings,
        user=user,
    )
