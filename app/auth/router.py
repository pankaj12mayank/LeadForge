from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.security import (
    create_csrf_token,
    create_session_token,
    hash_password,
    read_session_token,
    verify_csrf_token,
    verify_password as vp,
)
from app.config import settings
from app.db import SessionLocal
from app.models import (
    CreditLedger,
    Membership,
    Organization,
    Plan,
    Role,
    Subscription,
    SubStatus,
    User,
)
from app.services.email import send_email

router = APIRouter()

SESSION_NAME = "session"


def _render(request: Request, template: str, status_code: int = 200, user=None, **ctx) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("user", user)
    return HTMLResponse(
        templates.get_template(template).render(**ctx), status_code=status_code
    )


def verify_password(password: str, hashed: str) -> bool:
    return vp(password, hashed)


@router.get("/auth/login", name="login_page")
async def login_page(request: Request):
    return _render(request, "auth/login.html", csrf_token=create_csrf_token("login"))


@router.post("/auth/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password_hash):
            return HTMLResponse(
                "Invalid credentials", status_code=401, headers={"HX-Redirect": "/auth/login"}
            )
        if not user.is_active:
            return HTMLResponse(
                "Account disabled", status_code=403, headers={"HX-Redirect": "/auth/login"}
            )
        target = "/admin" if getattr(user, "role", None) in (Role.admin, "admin") else "/dashboard"
        resp = RedirectResponse(url=target, status_code=303)
        resp.set_cookie(
            SESSION_NAME,
            create_session_token(user.id),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="Lax",
            path="/",
            max_age=60 * 60 * 24 * 30,
        )
        return resp
    finally:
        db.close()


@router.post("/auth/logout")
async def logout():
    resp = RedirectResponse(url="/auth/login", status_code=303)
    resp.delete_cookie(SESSION_NAME, path="/")
    return resp


@router.get("/auth/signup", name="signup_page")
async def signup_page(request: Request):
    return _render(request, "auth/signup.html", csrf_token=create_csrf_token("signup"))


@router.post("/auth/signup")
async def signup(request: Request, email: str = Form(...), password: str = Form(...), name: str = Form("")):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return HTMLResponse("Email already registered", status_code=400, headers={"HX-Redirect": "/auth/signup"})
        plan = db.query(Plan).filter(Plan.code == "starter").first()
        trial_ends = datetime.now(timezone.utc) + timedelta(days=settings.TRIAL_DAYS)
        user = User(email=email, name=name or email, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        org = Organization(name=f"{email.split('@')[0]} Org", owner_id=user.id)
        db.add(org)
        db.flush()
        db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
        sub = Subscription(
            org_id=org.id,
            plan_id=plan.id if plan else None,
            status=SubStatus.trialing,
            trial_ends_at=trial_ends,
        )
        db.add(sub)
        db.flush()
        db.add(
            CreditLedger(
                org_id=org.id,
                delta=settings.TRIAL_CREDITS,
                reason="trial signup",
            )
        )
        db.commit()
        target = "/admin" if getattr(user, "role", None) in (Role.admin, "admin") else "/dashboard"
        resp = RedirectResponse(url=target, status_code=303)
        resp.set_cookie(
            SESSION_NAME,
            create_session_token(user.id),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="Lax",
            path="/",
            max_age=60 * 60 * 24 * 30,
        )
        return resp
    finally:
        db.close()


@router.get("/auth/forgot", name="forgot_page")
async def forgot_page(request: Request):
    return _render(request, "auth/forgot.html", csrf_token=create_csrf_token("forgot"))


@router.post("/auth/forgot")
async def forgot(request: Request, email: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            token = create_session_token(user.id)  # reuse as reset token (short max_age)
            reset_url = f"{settings.BASE_URL}/auth/reset?token={token}"
            send_email(
                email,
                "Reset your LeadForge password",
                f"Reset link: {reset_url}\nExpires in 60 minutes.",
            )
        return HTMLResponse("If the account exists, a reset link has been sent (dev: logged to console).")
    finally:
        db.close()


@router.get("/auth/reset", name="reset_page")
async def reset_page(request: Request, token: str = ""):
    return _render(request, "auth/reset.html", token=token)


@router.post("/auth/reset")
async def reset(request: Request, token: str = Form(...), password: str = Form(...)):
    uid = read_session_token(token, max_age=60 * 60)
    if not uid:
        return HTMLResponse("Invalid or expired token", status_code=400)
    db = SessionLocal()
    try:
        user = db.get(User, uid)
        if user:
            user.password_hash = hash_password(password)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/auth/login", status_code=303)
