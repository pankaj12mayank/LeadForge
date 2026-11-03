from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.sources.base import RawLead, Source

log = logging.getLogger("leadforge.sources.places")


class PlacesSource(Source):
    name = "places"
    pro_only = True

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=1, max=8))
    async def search(self, filters: dict, limit: int) -> list[RawLead]:
        if not self.api_key:
            return []
        query = " ".join(filters.get("keywords", [])) + " " + " ".join(filters.get("locations", []))
        query = query.strip()
        if not query:
            return []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/textsearch/json",
                    params={"query": query, "key": self.api_key},
                )
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("places search failed: %s", exc)
            return []
        leads: list[RawLead] = []
        for r in data.get("results", []) or []:
            leads.append(
                {
                    "name": r.get("name"),
                    "title": None,
                    "company": None,
                    "email": None,
                    "linkedin_url": None,
                    "location": r.get("formatted_address"),
                    "source": "places",
                    "raw": r,
                }
            )
        return leads[:limit]
