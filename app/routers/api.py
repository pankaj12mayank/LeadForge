from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, Lead

router = APIRouter()


def _org_from_api_key(x_api_key: str | None, db: Session):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    ak = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not ak:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return ak.org_id


@router.post("/api/v1/searches")
def api_create_search(x_api_key: str | None = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    org_id = _org_from_api_key(x_api_key, db)
    return {"org_id": org_id, "message": "use the web UI to create searches (API stub)"}


@router.get("/api/v1/leads")
def api_list_leads(x_api_key: str | None = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    org_id = _org_from_api_key(x_api_key, db)
    leads = (
        db.query(Lead)
        .filter(Lead.org_id == org_id)
        .order_by(Lead.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "leads": [
            {
                "id": l.id,
                "name": l.name,
                "company": l.company,
                "email": l.email,
                "score": l.score,
                "tier": l.tier,
                "status": l.status,
            }
            for l in leads
        ]
    }
