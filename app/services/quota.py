from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import CreditLedger, Organization, Subscription, SubStatus


def get_credits(org_id: int, db: Session) -> int:
    row = db.query(CreditLedger).filter(CreditLedger.org_id == org_id).all()
    return sum(r.delta for r in row)


def plan_monthly_credits(org_id: int, db: Session) -> int:
    sub = db.query(Subscription).filter(Subscription.org_id == org_id).order_by(Subscription.created_at.desc()).first()
    if not sub:
        return 0
    plan = db.query(__import__("app.models", fromlist=["Plan"]).Plan).get(sub.plan_id) if False else None
    from app.models import Plan

    plan = db.query(Plan).get(sub.plan_id)
    return plan.monthly_credits if plan else 0


def has_credits(org_id: int, amount: int, db: Session) -> bool:
    return get_credits(org_id, db) >= amount


def reserve_credits(org_id: int, amount: int, reason: str, db: Session, job_id: int | None = None) -> None:
    if amount <= 0:
        return
    if not has_credits(org_id, amount, db):
        raise ValueError(f"Insufficient credits: need {amount}, have {get_credits(org_id, db)}")
    db.add(CreditLedger(org_id=org_id, delta=-amount, reason=reason, job_id=job_id))
    db.commit()


def refund_credits(org_id: int, amount: int, reason: str, db: Session, job_id: int | None = None) -> None:
    if amount <= 0:
        return
    db.add(CreditLedger(org_id=org_id, delta=amount, reason=reason, job_id=job_id))
    db.commit()


def add_credits(org_id: int, amount: int, reason: str, db: Session) -> None:
    db.add(CreditLedger(org_id=org_id, delta=amount, reason=reason))
    db.commit()


def subscription_active(org_id: int, db: Session) -> bool:
    sub = (
        db.query(Subscription)
        .filter(Subscription.org_id == org_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if not sub:
        return False
    return sub.status in (SubStatus.trialing, SubStatus.active)
