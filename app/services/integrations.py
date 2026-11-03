from __future__ import annotations

import hashlib
import hmac
import json
import logging

import httpx

from app.config import settings

log = logging.getLogger("leadforge.integrations")


def verify_razorpay_signature(body: bytes, signature: str) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def push_leadops(leads: list[dict]) -> bool:
    if not settings.LEADOPS_URL or not settings.LEADOPS_TOKEN:
        return False
    try:
        async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.LEADOPS_URL.rstrip('/')}/leads",
                headers={"Authorization": f"Bearer {settings.LEADOPS_TOKEN}"},
                json={"leads": leads},
            )
        return resp.status_code < 300
    except Exception as exc:  # noqa: BLE001
        log.warning("leadops push failed: %s", exc)
        return False


async def push_webhook(url: str, payload: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        return resp.status_code < 300
    except Exception as exc:  # noqa: BLE001
        log.warning("webhook push failed: %s", exc)
        return False
