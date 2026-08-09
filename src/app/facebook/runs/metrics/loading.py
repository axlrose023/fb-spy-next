from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .normalization import clean, parse_datetime


def load_ads(run_dir: Path) -> list[dict[str, Any]]:
    for filename in ("ads.classified.json", "ads.json", "ads.partial.json"):
        path = run_dir / filename
        if not path.exists():
            continue
        payload = load_json(path, default=[])
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    return []


def load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def last_captured_at(ads: list[dict[str, Any]]) -> str | None:
    values = [
        value for ad in ads if (value := clean(ad.get("captured_at"))) is not None
    ]
    return max(values) if values else None


def elapsed_from_timestamps(
    started_at: str | None,
    finished_at: str | None,
) -> float | None:
    started = parse_datetime(started_at)
    finished = parse_datetime(finished_at)
    if not started or not finished:
        return None
    return max(0.0, (finished - started).total_seconds())
