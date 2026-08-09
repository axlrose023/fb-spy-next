from __future__ import annotations

import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager


class BrowserOperationDeadlineExceeded(BaseException):
    pass


@contextmanager
def hard_deadline(seconds: float, label: str) -> Iterator[None]:
    """Interrupt a blocking sync browser call on Unix without stopping the run."""
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
    started = time.monotonic()

    def expire(_signum: int, _frame: object) -> None:
        raise BrowserOperationDeadlineExceeded(label)

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        remaining, interval = previous_timer
        if remaining > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(1e-6, remaining - elapsed),
                interval,
            )
