from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base, Plan, User, Organization, Membership, Subscription, SubStatus

PLANS = [
    {
        "code": "starter",
        "name": "Starter",
        "price_inr": 999,
        "monthly_credits": 50,
        "seats": 1,
        "features": {
            "sources": ["apollo", "websearch"],
            "scoring": "basic",
            "saved_searches": False,
            "api_access": False,
            "opener": False,
        },
    },
    {
        "code": "pro",
        "name": "Pro",
        "price_inr": 2999,
        "monthly_credits": 300,
        "seats": 5,
        "features": {
            "sources": ["apollo", "websearch", "places"],
            "scoring": "full",
            "saved_searches": True,
            "api_access": True,
            "opener": True,
        },
    },
]


def seed_plans(db: Session) -> None:
    for p in PLANS:
        existing = db.query(Plan).filter(Plan.code == p["code"]).first()
        if existing:
            existing.name = p["name"]
            existing.price_inr = p["price_inr"]
            existing.monthly_credits = p["monthly_credits"]
            existing.seats = p["seats"]
            existing.features = p["features"]
        else:
            db.add(Plan(**p))
    db.commit()


def seed_admin(db: Session) -> None:
    email = settings.ADMIN_EMAIL
    password = settings.ADMIN_PASSWORD
    if not email or not password:
        print("ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping admin seed")
        return
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=settings.ADMIN_NAME, password_hash=hash_password(password), role="admin")
        db.add(user)
        db.flush()
        org = Organization(name="Admin Org", owner_id=user.id)
        db.add(org)
        db.flush()
        db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
        plan = db.query(Plan).filter(Plan.code == "pro").first()
        db.add(Subscription(org_id=org.id, plan_id=plan.id, status=SubStatus.active))
        db.commit()
        print(f"Seeded admin {email}")
    else:
        print("Admin already exists")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_plans(db)
        seed_admin(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
