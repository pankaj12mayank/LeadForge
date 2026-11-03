from __future__ import annotations

import smtplib
from email.message import EmailMessage
from app.config import settings


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.SMTP_HOST:
        print(f"[DEV EMAIL] to={to} subject={subject}\n{body}", flush=True)
        return
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as s:
        if settings.SMTP_TLS:
            s.starttls()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        s.send_message(msg)
