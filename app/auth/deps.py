from __future__ import annotations

from typing import Callable
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, Membership


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get("session")
    if not token:
        return None
    from app.auth.security import read_session_token

    uid = read_session_token(token)
    if not uid:
        return None
    user = db.get(User, uid)
    if not user or not user.is_active:
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return user


def current_org_id(user: User = Depends(require_user), db: Session = Depends(get_db)) -> int:
    m = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not m:
        raise HTTPException(status_code=400, detail="No organization")
    return m.org_id


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
