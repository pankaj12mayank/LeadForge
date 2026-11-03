from __future__ import annotations

from pydantic import BaseModel, Field


class LeadPlan(BaseModel):
    sources: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    target_count: int = Field(default=10, ge=1, le=500)
    notes: str = ""
