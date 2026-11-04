from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.auth.deps import current_org_id, require_user, require_user
from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Plan, Subscription, SubStatus
from app.services.integrations import verify_razorpay_signature
from app.services.quota import add_credits

router = APIRouter()


def _render(request: Request, template: str, status_code: int = 200, user=None, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", user)
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


@router.get("/billing/pricing")
def pricing_page(request: Request, user=Depends(require_user)):
    return _render(request, "pricing.html", settings=settings, user=user)


@router.post("/billing/subscribe")
def subscribe(request: Request, org_id: int = Depends(current_org_id), plan_code: str = "pro"):
    db = SessionLocal()
    try:
        sub = (
            db.query(Subscription)
            .filter(Subscription.org_id == org_id)
            .order_by(Subscription.created_at.desc())
            .first()
        )
        # Stub: in production create a Razorpay subscription here and redirect to checkout.
        if sub:
            sub.status = SubStatus.active
        else:
            from app.models import Plan, Subscription

            plan = db.query(Plan).filter(Plan.code == plan_code).first()
            db.add(
                Subscription(
                    org_id=org_id,
                    plan_id=plan.id,
                    status=SubStatus.active,
                    razorpay_subscription_id=f"sub_stub_{org_id}",
                )
            )
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/billing/portal", status_code=303)


@router.get("/billing/portal")
def billing_portal(request: Request, user=Depends(require_user), org_id: int = Depends(current_org_id), db: Session = Depends(get_db)):
    sub = (
        db.query(Subscription)
        .filter(Subscription.org_id == org_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    plan = db.get(Plan, sub.plan_id) if sub else None
    return _render(
        request,
        "portal.html",
        sub=sub,
        plan=plan,
        settings=settings,
        razorpay_key=settings.RAZORPAY_KEY_ID,
        mode=settings.RAZORPAY_MODE,
        user=user,
    )


@router.post("/billing/webhook")
async def razorpay_webhook(request: Request, x_razorpay_signature: str = Header(None)):
    body = await request.body()
    if not verify_razorpay_signature(body, x_razorpay_signature or ""):
        return PlainTextResponse("bad signature", status_code=400)
    payload = json.loads(body)
    event_id = payload.get("event", {}).get("id") if isinstance(payload.get("event"), dict) else None
    db = SessionLocal()
    try:
        from app.models import WebhookEvent

        if event_id:
            existing = db.query(WebhookEvent).filter(WebhookEvent.event_id == str(event_id)).first()
            if existing:
                return PlainTextResponse("ok")
            db.add(WebhookEvent(provider="razorpay", event_id=str(event_id), payload=payload))
        entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        sub_id = entity.get("id")
        status = entity.get("status")
        if sub_id:
            sub = db.query(__import__("app.models", fromlist=["Subscription"]).Subscription).filter(
                Subscription.razorpay_subscription_id == sub_id
            ).first()
            if sub:
                sub.status = {
                    "activated": SubStatus.active,
                    "charged": SubStatus.active,
                    "halted": SubStatus.past_due,
                    "cancelled": SubStatus.cancelled,
                    "completed": SubStatus.completed,
                }.get(status, sub.status)
                if status == "charged":
                    from app.services.quota import add_credits
                    plan = db.query(__import__("app.models", fromlist=["Plan"]).Plan).get(sub.plan_id)
                    if plan:
                        add_credits(sub.org_id, plan.monthly_credits, "razorpay charge", db)
                db.commit()
        db.commit()
    finally:
        db.close()
    return PlainTextResponse("ok")
