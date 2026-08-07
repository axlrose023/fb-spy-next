from __future__ import annotations

from .contracts import AdStatisticsReader
from .models import AdStatistics


class StatisticsService:
    def __init__(
        self,
        reader: AdStatisticsReader,
        *,
        facet_limit: int = 30,
    ) -> None:
        self._reader = reader
        self._facet_limit = facet_limit

    async def get_ads_stats(self) -> AdStatistics:
        return await self._reader.read_ads_statistics(facet_limit=self._facet_limit)
