from __future__ import annotations

import json
import logging
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel

from app.config import settings

log = logging.getLogger("leadforge.llm")

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMResult(Generic[T]):
    def __init__(self, obj: T | None, raw: str, provider: str, tokens: int = 0, cost_usd: float = 0.0):
        self.obj = obj
        self.raw = raw
        self.provider = provider
        self.tokens = tokens
        self.cost_usd = cost_usd


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)
        raw = raw[1] if len(raw) > 1 else raw[0]
        if raw.startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


async def call_json(
    system: str,
    user: str,
    schema: type[T],
    *,
    provider: str | None = None,
) -> LLMResult[T]:
    provider = provider or settings.LLM_PROVIDER
    raw = ""
    tokens = 0
    cost = 0.0

    if provider == "openai":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.LLM_TIMEOUT)
        last_err: str | None = None
        for attempt in range(settings.LLM_MAX_RETRIES):
            try:
                resp = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                raw = resp.choices[0].message.content or ""
                tokens = getattr(resp.usage, "total_tokens", 0) or 0
                cost = tokens * 0.00000015  # rough placeholder
                data = json.loads(_extract_json(raw))
                return LLMResult(schema.model_validate(data), raw, "openai", tokens, cost)
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                log.warning("openai attempt %s failed: %s", attempt + 1, last_err)
        raise LLMError(f"openai failed after {settings.LLM_MAX_RETRIES} attempts: {last_err}")

    if provider == "ollama":
        last_err = None
        for attempt in range(settings.LLM_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                    resp = await client.post(
                        f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat",
                        json={
                            "model": settings.OLLAMA_MODEL,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                            "stream": False,
                            "format": "json",
                        },
                    )
                resp.raise_for_status()
                raw = resp.json().get("message", {}).get("content", "")
                data = json.loads(_extract_json(raw))
                return LLMResult(schema.model_validate(data), raw, "ollama", 0, 0.0)
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                log.warning("ollama attempt %s failed: %s", attempt + 1, last_err)
        raise LLMError(f"ollama failed after {settings.LLM_MAX_RETRIES} attempts: {last_err}")

    # provider == "none": deterministic placeholder, no LLM call
    return LLMResult(None, "", "none", 0, 0.0)
