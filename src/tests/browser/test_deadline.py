from __future__ import annotations

import signal
import time
from typing import Any

import pytest

import app.browser.deadline as deadline_module
from app.browser import BrowserOperationDeadlineExceeded, hard_deadline
from app.services import facebook_runner

pytestmark = pytest.mark.unit


def test_hard_deadline_interrupts_blocking_operation() -> None:
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("SIGALRM is unavailable on this platform")
    started = time.monotonic()

    with pytest.raises(BrowserOperationDeadlineExceeded, match="blocked operation"):
        with hard_deadline(0.05, "blocked operation"):
            time.sleep(5)

    assert time.monotonic() - started < 1


def test_non_positive_deadline_is_a_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*_: object) -> None:
        pytest.fail("signal timer should not be touched")

    monkeypatch.setattr(deadline_module.signal, "setitimer", unexpected_call)

    with hard_deadline(0, "disabled"):
        pass


def test_hard_deadline_restores_previous_handler_and_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_handler = object()
    timer_calls: list[tuple[int, float, float]] = []
    handler_calls: list[tuple[int, Any]] = []
    monotonic_values = iter((10.0, 12.0))

    monkeypatch.setattr(
        deadline_module.signal,
        "getsignal",
        lambda _signal: previous_handler,
    )

    def set_timer(
        which: int,
        seconds: float,
        interval: float = 0.0,
    ) -> tuple[float, float]:
        timer_calls.append((which, seconds, interval))
        return (5.0, 0.25) if len(timer_calls) == 1 else (0.0, 0.0)

    def set_handler(which: int, handler: Any) -> Any:
        handler_calls.append((which, handler))
        return previous_handler

    monkeypatch.setattr(deadline_module.signal, "setitimer", set_timer)
    monkeypatch.setattr(deadline_module.signal, "signal", set_handler)
    monkeypatch.setattr(
        deadline_module.time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    with hard_deadline(4.0, "nested operation"):
        pass

    assert timer_calls == [
        (signal.ITIMER_REAL, 0, 0.0),
        (signal.ITIMER_REAL, 4.0, 0.0),
        (signal.ITIMER_REAL, 0, 0.0),
        (signal.ITIMER_REAL, 3.0, 0.25),
    ]
    assert handler_calls[0][0] == signal.SIGALRM
    assert callable(handler_calls[0][1])
    assert handler_calls[1] == (signal.SIGALRM, previous_handler)


def test_runner_private_deadline_aliases_preserve_identity() -> None:
    assert facebook_runner._hard_deadline is hard_deadline
    assert (
        facebook_runner._OperationDeadlineExceeded is BrowserOperationDeadlineExceeded
    )
