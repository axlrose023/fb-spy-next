from __future__ import annotations

import pytest

from app.ad_library.statistics import AdStatistics, StatisticsService

pytestmark = pytest.mark.unit


def empty_statistics() -> AdStatistics:
    return AdStatistics(
        total_ads=0,
        link_ads=0,
        resolved_ads=0,
        video_ads=0,
        bad_screenshots=0,
        by_type=(),
        by_format=(),
        by_vertical=(),
        by_country=(),
        by_language=(),
        by_platform=(),
        by_placement=(),
        by_domain=(),
        by_advertiser=(),
        by_cta=(),
    )


class RecordingReader:
    def __init__(self, result: AdStatistics) -> None:
        self.result = result
        self.limits: list[int] = []

    async def read_ads_statistics(self, *, facet_limit: int) -> AdStatistics:
        self.limits.append(facet_limit)
        return self.result


async def test_service_delegates_domain_query_and_facet_limit() -> None:
    expected = empty_statistics()
    reader = RecordingReader(expected)
    service = StatisticsService(reader, facet_limit=12)

    result = await service.get_ads_stats()

    assert result is expected
    assert reader.limits == [12]
