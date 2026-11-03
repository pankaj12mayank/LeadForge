from __future__ import annotations

import uuid
from app.models import Lead, Organization, Subscription, SubStatus, User, Plan
from app.services.merge import merge_incoming, merge_against_org
from app.services.planner import plan_query
from app.services.quota import add_credits, get_credits, has_credits, reserve_credits, refund_credits
from app.services.score import score_leads
from app.services.integrations import verify_razorpay_signature


def _org(db, code="starter", name="Test Org"):
    user = User(email=f"user{uuid.uuid4().hex}@x.test", password_hash="x", name=name)
    db.add(user)
    db.flush()
    org = Organization(name=name, owner_id=user.id)
    db.add(org)
    db.flush()
    plan = db.query(Plan).filter(Plan.code == code).first()
    if plan is None:
        plan = Plan(code=code, name=code.title(), price_inr=0, monthly_credits=100, seats=5, features={})
        db.add(plan)
        db.flush()
    db.add(Subscription(org_id=org.id, plan_id=plan.id, status=SubStatus.active))
    db.commit()
    return org


def test_merge_dedupe_within_batch():
    leads = [
        {"email": "a@x.com", "name": "A"},
        {"email": "A@X.COM ", "name": "A dup"},
        {"linkedin_url": "https://linkedin.com/in/b", "name": "B"},
        {"linkedin_url": "https://linkedin.com/in/B", "name": "B dup"},
        {"domain": "x.com", "name": "C"},
        {"domain": "X.COM", "name": "C dup"},
        {"name": "no key"},
        {"name": "no key dup"},
    ]
    out = merge_incoming(list(leads))
    emails = {l["email"] for l in out if l.get("email")}
    linked = {l["linkedin_url"] for l in out if l.get("linkedin_url")}
    assert len(out) == 4  # a, b, c, one no-key


def test_merge_against_org(db):
    org = _org(db)
    existing = Lead(org_id=org.id, name="Existing", email="keep@out.com")
    db.add(existing)
    db.commit()
    incoming = [
        {"email": "keep@out.com", "name": "Existing"},
        {"email": "new@out.com", "name": "New"},
    ]
    out = merge_against_org(incoming, org.id, db)
    assert len(out) == 1
    assert out[0]["email"] == "new@out.com"


def test_quota_reserve_refund(db):
    org = _org(db)
    add_credits(org.id, 10, "topup", db)
    assert get_credits(org.id, db) == 10
    reserve_credits(org.id, 4, "job", db)
    assert get_credits(org.id, db) == 6
    assert has_credits(org.id, 6, db)
    assert not has_credits(org.id, 7, db)
    refund_credits(org.id, 4, "cancel", db)
    assert get_credits(org.id, db) == 10


def test_planner_rule_based():
    import asyncio

    plan = asyncio.run(plan_query("India fintech startups founders manual reporting, 20 leads", features={"sources": ["apollo", "websearch"]}))
    assert "websearch" in plan.sources
    assert plan.target_count >= 1


def test_planner_drops_pro_source_for_starter():
    import asyncio

    plan = asyncio.run(plan_query("x", features={"sources": ["apollo", "websearch"]}))
    assert "places" not in plan.sources


def test_score_rule_based():
    import asyncio

    leads = [{"name": "Ada Founder", "title": "CEO", "company": "Acme", "email": "ada@acme.com", "linkedin_url": "https://linkedin.com/in/ada"}]
    out = asyncio.run(score_leads(leads, is_pro=False))
    assert out[0]["tier"] in ("hot", "warm", "cold")
    assert out[0]["opener"] is None


def test_score_pro_opener():
    import asyncio

    leads = [{"name": "Ada Founder", "title": "CEO", "company": "Acme", "email": "ada@acme.com"}]
    out = asyncio.run(score_leads(leads, is_pro=True))
    assert out[0]["opener"] is not None


def test_tenant_isolation(db):
    org_a = _org(db, name="Org A")
    org_b = _org(db, name="Org B")
    db.add(Lead(org_id=org_a.id, name="Lead A", email="a@a.com"))
    db.add(Lead(org_id=org_b.id, name="Lead B", email="b@b.com"))
    db.commit()
    a_leads = db.query(Lead).filter(Lead.org_id == org_a.id).all()
    b_leads = db.query(Lead).filter(Lead.org_id == org_b.id).all()
    assert len(a_leads) == 1 and a_leads[0].email == "a@a.com"
    assert len(b_leads) == 1 and b_leads[0].email == "b@b.com"


def test_razorpay_signature():
    secret = "whsec_test"
    body = b'{"id":"evt_1"}'
    import hmac, hashlib

    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_razorpay_signature(body, sig) is True
    assert verify_razorpay_signature(body, "wrong") is False
