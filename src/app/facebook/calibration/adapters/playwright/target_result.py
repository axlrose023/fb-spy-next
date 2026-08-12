from __future__ import annotations

from typing import Any


def target_failure_reason(
    engagement: dict[str, Any],
    *,
    post_viewed: bool,
    funnel_required: bool,
    funnel_ok: bool,
) -> str:
    if not post_viewed:
        return f"saved Facebook post view failed: {engagement.get('view')}"
    if funnel_required and not funnel_ok:
        funnel: dict[str, Any] = next(
            (
                action
                for action in engagement.get("actions", [])
                if action.get("action") == "offer_funnel"
            ),
            {},
        )
        return f"offer funnel incomplete: status={funnel.get('status') or 'missing'}"
    return "calibration target did not satisfy its completion policy"
