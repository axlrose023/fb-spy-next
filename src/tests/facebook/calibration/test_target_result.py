from __future__ import annotations

import pytest

from app.facebook.calibration.adapters.playwright.target_result import (
    target_failure_reason,
)

pytestmark = pytest.mark.unit


def test_target_failure_reports_post_view_failure_first() -> None:
    engagement = {"view": {"status": "root_not_found"}, "actions": []}

    assert target_failure_reason(
        engagement,
        post_viewed=False,
        funnel_required=True,
        funnel_ok=False,
    ) == "saved Facebook post view failed: {'status': 'root_not_found'}"


def test_target_failure_reports_incomplete_funnel_after_post_view() -> None:
    engagement = {
        "view": {"status": "viewing"},
        "actions": [{"action": "offer_funnel", "status": "landing_viewed"}],
    }

    assert target_failure_reason(
        engagement,
        post_viewed=True,
        funnel_required=True,
        funnel_ok=False,
    ) == "offer funnel incomplete: status=landing_viewed"
