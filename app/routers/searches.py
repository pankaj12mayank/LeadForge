from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import current_user, current_org_id, require_user
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Job, JobStatus, Search
from app.services.quota import has_credits

router = APIRouter()


def _render(request: Request, template: str, status_code: int = 200, user=None, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", user)
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


@router.get("/searches")
def searches_list(request: Request, user=Depends(require_user), org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    searches = (
        db.query(Search)
        .filter(Search.org_id == org_id)
        .order_by(Search.created_at.desc())
        .all()
    )
    return _render(request, "searches.html", searches=searches, settings=settings, user=user)


@router.post("/searches")
def create_search(
    request: Request,
    user=Depends(require_user),
    org_id: int = Depends(current_org_id),
    query: str = Form(...),
    target_count: int = Form(10),
    db: Session = Depends(get_db),
):
    target_count = max(1, min(target_count, 500))
    if not has_credits(org_id, target_count, db):
        return HTMLResponse(
            "Insufficient credits", status_code=400, headers={"HX-Redirect": "/searches"}
        )
    search = Search(org_id=org_id, user_id=user.id, query=query)
    db.add(search)
    db.flush()
    job = Job(
        org_id=org_id,
        search_id=search.id,
        type="search",
        status=JobStatus.queued,
        run_after=datetime.now(timezone.utc),
        result_summary={"target_count": target_count},
    )
    db.add(job)
    db.commit()
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@router.get("/jobs/{job_id}")
def job_page(request: Request, job_id: int, user=Depends(require_user), org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.org_id != org_id:
        return HTMLResponse("Not found", status_code=404)
    return _render(request, "job.html", job=job, settings=settings, user=user)


@router.get("/jobs/{job_id}/status")
def job_status(request: Request, job_id: int, user=Depends(require_user), org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.org_id != org_id:
        return HTMLResponse("Not found", status_code=404)
    return _render(request, "job_status.html", job=job, settings=settings, user=user)
