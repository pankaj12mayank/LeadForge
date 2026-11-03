from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.sources.base import RawLead, Source

log = logging.getLogger("leadforge.sources.websearch")


class WebSearchSource(Source):
    name = "websearch"
    pro_only = False

    def __init__(self, tavily_key: str | None, serper_key: str | None):
        self.tavily_key = tavily_key
        self.serper_key = serper_key

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=1, max=8))
    async def search(self, filters: dict, limit: int) -> list[RawLead]:
        query = " ".join(filters.get("keywords", [])) + " " + " ".join(filters.get("locations", []))
        query = query.strip()
        if not query or (not self.tavily_key and not self.serper_key):
            return []
        if self.tavily_key:
            return await self._tavily(query, limit)
        return await self._serper(query, limit)

    async def _tavily(self, query: str, limit: int) -> list[RawLead]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": self.tavily_key, "query": query, "max_results": limit},
                )
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("tavily search failed: %s", exc)
            return []
        leads: list[RawLead] = []
        for r in data.get("results", []) or []:
            leads.append(
                {
                    "name": r.get("title"),
                    "title": None,
                    "company": None,
                    "email": None,
                    "linkedin_url": r.get("url"),
                    "location": None,
                    "source": "websearch",
                    "raw": r,
                }
            )
        return leads[:limit]

    async def _serper(self, query: str, limit: int) -> list[RawLead]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": self.serper_key, "Content-Type": "application/json"},
                    json={"q": query, "num": limit},
                )
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("serper search failed: %s", exc)
            return []
        leads: list[RawLead] = []
        for r in (data.get("organic") or [])[:limit]:
            leads.append(
                {
                    "name": r.get("title"),
                    "title": None,
                    "company": None,
                    "email": None,
                    "linkedin_url": r.get("link"),
                    "location": None,
                    "source": "websearch",
                    "raw": r,
                }
            )
        return leads
