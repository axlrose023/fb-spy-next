from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def source_path(run_dir: Path, stage: str, source: Path | None) -> Path:
    if source is not None:
        return source.expanduser().resolve()
    if stage == "finalize":
        return run_dir / "ads.enriched.json"
    if stage == "resolve-holds":
        return run_dir / "ads.isolated.json"
    return run_dir / "ads.json"


def classification_is_complete(path: Path, expected_count: int) -> bool:
    if not path.exists():
        return False
    try:
        ads = load_ads(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return len(ads) == expected_count and all(
        isinstance(ad.get("relevance"), dict)
        and ad["relevance"].get("result") in {"relevant", "not_relevant"}
        for ad in ads
    )


def load_ads(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return [item for item in payload if isinstance(item, dict)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def append_json_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def is_relevant(raw: dict[str, Any]) -> bool:
    relevance = raw.get("relevance")
    return isinstance(relevance, dict) and relevance.get("result") == "relevant"


def is_not_relevant(raw: dict[str, Any]) -> bool:
    relevance = raw.get("relevance")
    return isinstance(relevance, dict) and relevance.get("result") == "not_relevant"
