from __future__ import annotations

from typing import Protocol

from .models import AdStatistics


class AdStatisticsReader(Protocol):
    async def read_ads_statistics(self, *, facet_limit: int) -> AdStatistics: ...
