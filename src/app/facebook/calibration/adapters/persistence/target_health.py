from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .artifacts import write_json_atomic
from .target_mapping import clean


def quarantined_facebook_post_urls(
    path: Path | None,
    *,
    now: datetime | None = None,
) -> set[str]:
    payload = _load_target_health(path)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    quarantined: set[str] = set()
    for url, raw in payload.get("targets", {}).items():
        if not isinstance(raw, dict):
            continue
        until = _aware_datetime(raw.get("quarantined_until"))
        if until is not None and until > current:
            quarantined.add(str(url))
    return quarantined


def record_facebook_post_target_result(
    path: Path | None,
    result: dict[str, Any],
    *,
    now: datetime | None = None,
    failure_threshold: int = 2,
    quarantine_days: int = 7,
) -> None:
    if path is None:
        return
    url = clean(result.get("url"))
    if not url:
        return
    payload = _load_target_health(path)
    targets = payload.setdefault("targets", {})
    if result.get("ok") is True:
        if targets.pop(url, None) is not None:
            payload["updated_at"] = (now or datetime.now(UTC)).isoformat()
            write_json_atomic(path, payload)
        return
    match = result.get("match")
    if not isinstance(match, dict) or match.get("status") != "post_not_found":
        return

    current = (now or datetime.now(UTC)).astimezone(UTC)
    previous = targets.get(url) if isinstance(targets.get(url), dict) else {}
    failures = max(0, _int_or_none(previous.get("consecutive_failures")) or 0) + 1
    record = {
        "consecutive_failures": failures,
        "last_failed_at": current.isoformat(),
        "last_status": "post_not_found",
    }
    if failures >= max(1, failure_threshold):
        record["quarantined_until"] = (
            current + timedelta(days=max(1, quarantine_days))
        ).isoformat()
    targets[url] = record
    payload["updated_at"] = current.isoformat()
    write_json_atomic(path, payload)


def _aware_datetime(value: Any) -> datetime | None:
    value = clean(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_target_health(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"version": 1, "targets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "targets": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("targets"), dict):
        return {"version": 1, "targets": {}}
    payload.setdefault("version", 1)
    return payload


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
