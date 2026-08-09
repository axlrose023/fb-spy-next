from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..models import CollectedAd, utc_now

COLLECTOR_METRIC_VERSION = 2

BROWSER_OPERATION_TIMEOUT_REASONS = frozenset(
    {
        "resolve_timeout",
        "video_timeout",
    }
)


def write_ads(path: Path, ads: dict[str, CollectedAd]) -> None:
    payload = json.dumps(
        [asdict(ad) for ad in ads.values()],
        ensure_ascii=False,
        indent=2,
    )
    write_text_atomic(path, payload)


def write_json_atomic(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def write_run_meta(run_dir: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(run_dir / "run_meta.json", payload)


def octo_start_failure_reason(error: BaseException) -> str:
    if "profiles.proxy_error" in str(error):
        return "octo_proxy_error"
    return "octo_start_error"


def write_octo_start_failure(
    run_dir: Path,
    *,
    profile_uuid: str,
    octo_host: str,
    octo_port: int,
    octo_headless: bool,
    requested_minutes: float,
    started_at: str,
    elapsed_seconds: float,
    error: BaseException,
    clock: Callable[[], str] = utc_now,
    metric_version: int = COLLECTOR_METRIC_VERSION,
) -> str:
    reason = octo_start_failure_reason(error)
    finished_at = clock()
    write_run_meta(
        run_dir,
        {
            "collector_metric_version": metric_version,
            "octo_profile_uuid": profile_uuid,
            "octo_host": octo_host,
            "octo_port": octo_port,
            "octo_headless": octo_headless,
            "started_at": started_at,
            "finished_at": finished_at,
            "start_failure": reason,
        },
    )
    write_json_atomic(
        run_dir / "summary.json",
        {
            "collector_metric_version": metric_version,
            "requested_minutes": requested_minutes,
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": max(0.0, elapsed_seconds),
            "scrolls": 0,
            "refreshes": 0,
            "captured_candidates": 0,
            "stop_reason": reason,
        },
    )
    return reason


def fast_exit_after_browser_operation_timeout(run_dir: Path) -> None:
    """Avoid a wedged Playwright shutdown after its driver was interrupted."""
    try:
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    reason = str(summary.get("stop_reason") or "")
    if reason not in BROWSER_OPERATION_TIMEOUT_REASONS:
        return
    print(
        f"[runner] {reason} artifacts saved; exiting before Playwright cleanup",
        flush=True,
    )
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
