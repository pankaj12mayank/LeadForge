from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.config import settings
from app.db import get_db
from app.models import Plan

router = APIRouter()


def _render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", current_user(request))
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


@router.get("/", name="landing")
def landing(request: Request, db: Session = Depends(get_db)):
    plans = db.query(Plan).order_by(Plan.price_inr).all()
    return _render(request, "landing.html", plans=plans, settings=settings)


@router.get("/pricing", name="pricing")
def pricing(request: Request, db: Session = Depends(get_db)):
    plans = db.query(Plan).order_by(Plan.price_inr).all()
    return _render(request, "pricing.html", plans=plans, settings=settings)


@router.get("/privacy", name="privacy")
def privacy(request: Request):
    return _render(request, "privacy.html", settings=settings)


@router.get("/terms", name="terms")
def terms(request: Request):
    return _render(request, "terms.html", settings=settings)
