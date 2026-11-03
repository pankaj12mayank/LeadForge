from __future__ import annotations

from app.config import settings
from app.services.sources.apollo import ApolloSource
from app.services.sources.base import Source
from app.services.sources.places import PlacesSource
from app.services.sources.websearch import WebSearchSource


def get_sources(features: dict) -> list[Source]:
    allowed = set(features.get("sources", ["apollo", "websearch"]))
    sources: list[Source] = []
    if "apollo" in allowed:
        sources.append(ApolloSource(settings.APOLLO_API_KEY, settings.APOLLO_BASE_URL))
    if "websearch" in allowed:
        sources.append(WebSearchSource(settings.TAVILY_API_KEY, settings.SERPER_API_KEY))
    if "places" in allowed:
        sources.append(PlacesSource(settings.GOOGLE_PLACES_API_KEY))
    return sources
