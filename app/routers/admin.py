from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import require_admin
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Job, JobStatus, Organization, Subscription, User

router = APIRouter()


def _render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", require_admin(request.state.user) if hasattr(request.state, "user") else None)
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


@router.get("/admin")
def admin_overview(
    request: Request,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return HTMLResponse(
        "<h1>Admin</h1><p>users: "
        f"{db.query(User).count()}</p><p>orgs: {db.query(Organization).count()}</p>"
        f"<p>jobs: {db.query(Job).count()}</p><p><a href='/dashboard'>back</a></p>"
    )
