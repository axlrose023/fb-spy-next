from __future__ import annotations

import pytest

pytestmark = pytest.mark.contract


def test_worker_and_legacy_taskiq_entrypoints_share_runtime() -> None:
    from app import tiq, worker
    from app.tasks import analyze_facebook_ad_relevance, health_check

    assert tiq.broker is worker.broker
    assert tiq.scheduler is worker.scheduler
    assert tiq.container is worker.container
    assert tiq.redis_async_result is worker.redis_async_result
    assert worker.broker.find_task("facebook_ad_relevance") is (
        analyze_facebook_ad_relevance
    )
    assert worker.broker.find_task(health_check.task_name) is health_check
