from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth.deps import current_org_id, require_user
from app.config import settings
from app.db import get_db
from app.models import Lead, Plan, Subscription
from app.services.exporter import export_csv, export_xlsx
from app.services.quota import get_credits

router = APIRouter()


def _render(request: Request, template: str, status_code: int = 200, user=None, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", user)
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


@router.get("/leads")
def leads_list(
    request: Request,
    user=Depends(require_user),
    org_id: int = Depends(current_org_id),
    q: str | None = None,
    tier: str | None = None,
    status: str | None = None,
    sort: str = "score",
    page: int = 1,
    db: Session = Depends(get_db),
):
    query = db.query(Lead).filter(Lead.org_id == org_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Lead.name.ilike(like))
            | (Lead.company.ilike(like))
            | (Lead.email.ilike(like))
        )
    if tier:
        query = query.filter(Lead.tier == tier)
    if status:
        query = query.filter(Lead.status == status)
    if sort == "score":
        query = query.order_by(Lead.score.desc().nullslast(), Lead.created_at.desc())
    else:
        query = query.order_by(Lead.created_at.desc())

    PAGE_SIZE = 8
    total_leads = query.count()
    total_pages = max(1, (total_leads + PAGE_SIZE - 1) // PAGE_SIZE) if total_leads > 0 else 1
    page = max(1, min(page, total_pages))
    leads = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

    credits = get_credits(org_id, db)
    sub = (
        db.query(Subscription)
        .filter(Subscription.org_id == org_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    plan = db.get(Plan, sub.plan_id) if sub else None

    return _render(
        request,
        "leads.html",
        active_page="leads",
        page_title="Leads",
        page_sub=f"{total_leads} leads sourced across your workspace",
        leads=leads,
        total_leads=total_leads,
        page=page,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        q=q or "",
        tier=tier or "",
        status=status or "",
        sort=sort,
        settings=settings,
        user=user,
        credits=credits,
        sub=sub,
        plan=plan,
    )


@router.post("/leads/bulk")
def bulk_status(
    request: Request,
    org_id: int = Depends(current_org_id),
    ids: list[int] = Form([]),
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    if ids:
        db.query(Lead).filter(Lead.org_id == org_id, Lead.id.in_(ids)).update(
            {Lead.status: status}, synchronize_session=False
        )
        db.commit()
    trigger_json = '{"toast":{"kind":"ok","title":"Status updated","msg":"Marked as ' + status + '"}}'
    target_url = request.headers.get("referer") or "/leads"
    return RedirectResponse(url=target_url, status_code=303, headers={"HX-Trigger": trigger_json})


@router.get("/leads/export")
def export_leads(
    request: Request,
    fmt: str = "xlsx",
    org_id: int = Depends(current_org_id),
    db: Session = Depends(get_db),
):
    leads = db.query(Lead).filter(Lead.org_id == org_id).order_by(Lead.created_at.desc()).all()
    rows = []
    for l in leads:
        rows.append(
            {
                "name": l.name,
                "title": l.title,
                "company": l.company,
                "domain": l.domain,
                "email": l.email,
                "email_status": l.email_status,
                "phone": l.phone,
                "linkedin_url": l.linkedin_url,
                "location": l.location,
                "source": l.source,
                "score": l.score,
                "tier": l.tier,
                "pain_point": l.pain_point,
                "reason": l.reason,
                "opener": l.opener,
                "status": l.status,
                "created_at": str(l.created_at),
            }
        )
    if fmt == "csv":
        data = export_csv(rows)
        media = "text/csv"
        name = "leads.csv"
    else:
        data = export_xlsx(rows)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        name = "leads.xlsx"
    return StreamingResponse(
        iter([data]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
