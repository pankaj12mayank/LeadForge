from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.sources.base import RawLead, Source

log = logging.getLogger("leadforge.sources.apollo")


class ApolloSource(Source):
    name = "apollo"
    pro_only = False

    def __init__(self, api_key: str | None, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=1, max=8))
    async def search(self, filters: dict, limit: int) -> list[RawLead]:
        if not self.api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{self.base_url}/mixed_search/search",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"q_keywords": filters.get("keywords", ""), "page": 1, "per_page": min(limit, 100)},
                )
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("apollo search failed: %s", exc)
            return []
        leads: list[RawLead] = []
        for item in data.get("results", []) or data.get("people", []) or []:
            leads.append(
                {
                    "name": item.get("name") or item.get("first_name") or item.get("title"),
                    "title": item.get("title") or item.get("role"),
                    "company": item.get("company") or item.get("organization"),
                    "email": item.get("email"),
                    "linkedin_url": item.get("linkedin_url") or item.get("linkedin_profile_url"),
                    "location": item.get("location") or item.get("city"),
                    "source": "apollo",
                    "raw": item,
                }
            )
        return leads[:limit]
