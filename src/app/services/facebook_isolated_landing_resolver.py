"""Compatibility CLI for isolated relevance evidence resolution."""

from __future__ import annotations

from typing import Any

from app.facebook.relevance.adapters.anonymous_post import (
    CalibrationTarget as _CalibrationTarget,
)
from app.facebook.relevance.adapters.anonymous_post import (
    wait_for_anonymous_post_cta,
)
from app.facebook.relevance.adapters.isolation import host_is_public
from app.facebook.relevance.evidence.browser_command import main
from app.facebook.relevance.evidence.policy import (
    isolated_external_url as _isolated_external_url,
)
from app.facebook.relevance.evidence.policy import (
    resolution_candidate,
    summarize_isolated_resolutions,
)
from app.services import facebook_runner

CalibrationTarget = _CalibrationTarget
_host_is_public = host_is_public
_wait_for_anonymous_post_cta = wait_for_anonymous_post_cta


def isolated_external_url(value: Any) -> tuple[str, str]:
    return _isolated_external_url(value, host_is_public=_host_is_public)


def _resolution_candidate(raw: dict[str, Any]) -> tuple[str, str, str]:
    candidate = resolution_candidate(raw, host_is_public=_host_is_public)
    return candidate.source, candidate.target, candidate.issue


def _summary(rows: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    return summarize_isolated_resolutions(
        rows,
        status=status,
        finished_at=facebook_runner.utc_now(),
    )
if __name__ == "__main__":
    raise SystemExit(main())
