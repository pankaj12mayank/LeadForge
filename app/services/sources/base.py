from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

RawLead = dict[str, Any]


class SourceError(RuntimeError):
    pass


class Source(ABC):
    name: str = "base"
    pro_only: bool = False

    @abstractmethod
    async def search(self, filters: dict, limit: int) -> list[RawLead]:
        ...
