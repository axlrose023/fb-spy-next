from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.ad_library.ads import Ad

from ...adapters.persistence import FacebookRun

logger = logging.getLogger("app.services.facebook.importer")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def write_filter_outputs(
    ads_json_path: Path,
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    raw_total: int,
) -> None:
    unfiltered_path = ads_json_path.parent / "ads.unfiltered.json"
    if raw_total and not unfiltered_path.exists():
        ads_json_path.replace(unfiltered_path)
    write_json_atomic(ads_json_path, accepted)
    write_json_atomic(ads_json_path.parent / "ads.rejected.json", rejected)


def load_run_meta(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read FB run metadata path=%s", path)
        return {}
    if not isinstance(data, dict):
        logger.warning("FB run metadata expected object path=%s", path)
        return {}
    return data


def apply_run_stats(
    run: FacebookRun,
    *,
    run_dir: Path,
    ads_json_path: Path,
    ads: list[Ad],
) -> None:
    run.ads_json_path = str(ads_json_path)
    run.runner_run_dir = str(run_dir)
    run.debug_dir = str(run_dir / "debug") if (run_dir / "debug").exists() else None
    run.total_ads = len(ads)
    run.link_ads = sum(1 for ad in ads if ad.ad_type == "link")
    run.resolved_ads = sum(1 for ad in ads if ad.landing_full)
    run.video_ads = sum(1 for ad in ads if ad.has_video or ad.ad_type == "video")
    run.bad_screenshots = sum(1 for ad in ads if ad.screenshot_ok is False)
