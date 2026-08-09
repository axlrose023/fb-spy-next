from __future__ import annotations

_stop_requested = False


def request_stop(signum: int, _frame: object) -> None:
    global _stop_requested
    _stop_requested = True
    raise KeyboardInterrupt(f"signal {signum}")


def stop_requested() -> bool:
    return _stop_requested


def reset_stop_request() -> None:
    global _stop_requested
    _stop_requested = False
