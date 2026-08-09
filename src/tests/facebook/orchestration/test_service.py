from __future__ import annotations

import pytest

from app.facebook.orchestration import (
    OrchestrationRunHooks,
    OrchestrationRunRequest,
    OrchestrationService,
)

pytestmark = pytest.mark.unit


class RunHarness:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.discovery_error: Exception | None = None

    def discover(self) -> None:
        self.calls.append("discover")
        if self.discovery_error is not None:
            raise self.discovery_error

    def run_once(self) -> int:
        self.calls.append("once")
        return 11

    def run_continuously(self) -> int:
        self.calls.append("continuous")
        return 22

    def service(self) -> OrchestrationService:
        return OrchestrationService(
            OrchestrationRunHooks(
                discover_profiles=self.discover,
                run_once=self.run_once,
                run_continuously=self.run_continuously,
            )
        )


def test_one_shot_discovers_before_running_scheduler() -> None:
    harness = RunHarness()

    result = harness.service().run(OrchestrationRunRequest(continuous=False))

    assert result == 11
    assert harness.calls == ["discover", "once"]


def test_continuous_mode_selects_only_continuous_scheduler() -> None:
    harness = RunHarness()

    result = harness.service().run(OrchestrationRunRequest(continuous=True))

    assert result == 22
    assert harness.calls == ["discover", "continuous"]


def test_discovery_failure_propagates_without_starting_scheduler() -> None:
    harness = RunHarness()
    harness.discovery_error = RuntimeError("Octo unavailable")

    with pytest.raises(RuntimeError, match="Octo unavailable"):
        harness.service().run(OrchestrationRunRequest(continuous=False))

    assert harness.calls == ["discover"]
