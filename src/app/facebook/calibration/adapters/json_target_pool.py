from __future__ import annotations

import json
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from app.facebook.profiles import Profile

from ..planning import (
    calibration_pool_name,
    is_direct_calibration_target,
    is_relevant_ad,
    merge_calibration_ads,
)


class SavedTargetLoader(Protocol):
    def __call__(
        self,
        ads_json_paths: list[Path],
        *,
        country: str | None,
        limit: int,
        excluded_urls: set[str],
        include_direct_offers: bool,
    ) -> list[Any]: ...


class JsonCalibrationTargetPool:
    def __init__(
        self,
        target_loader: SavedTargetLoader,
        quarantine_loader: Callable[[Path | None], set[str]],
        *,
        lock: AbstractContextManager[object] | None = None,
    ) -> None:
        self._target_loader = target_loader
        self._quarantine_loader = quarantine_loader
        self._lock = lock or threading.Lock()

    def count(
        self,
        profile: Profile,
        collect_dir: Path,
        root_dir: Path | None = None,
    ) -> int:
        paths = self.source_paths(profile, collect_dir, root_dir)
        if not paths:
            return 0
        country = None if profile.no_country_filter else profile.expected_country
        try:
            return len(
                self._target_loader(
                    paths,
                    country=country,
                    limit=10_000,
                    include_direct_offers=True,
                    excluded_urls=self._quarantine_loader(
                        collect_dir.parent / "calibration_target_health.json"
                    ),
                )
            )
        except Exception:
            return 0

    def source_paths(
        self,
        profile: Profile,
        collect_dir: Path,
        root_dir: Path | None = None,
    ) -> list[Path]:
        paths: list[Path] = []
        fresh = collect_dir / "ads.relevant.json"
        if fresh.exists() and self.has_direct_relevant_ads(fresh):
            paths.append(fresh)
        active_root = root_dir or (
            collect_dir.parents[2] if len(collect_dir.parents) >= 3 else None
        )
        pool_candidates = [collect_dir.parent / "calibration_pool.json"]
        if active_root and profile.expected_country:
            pool_candidates.append(
                active_root
                / "calibration_pools"
                / f"{calibration_pool_name(profile.expected_country)}.json"
            )
        for candidate in pool_candidates:
            if (
                candidate.exists()
                and candidate not in paths
                and self.has_direct_relevant_ads(candidate)
            ):
                paths.append(candidate)
        for value in profile.calibration_ads_json:
            path = Path(value).expanduser()
            relevant_variant = path.with_name("ads.relevant.json")
            candidate = relevant_variant if relevant_variant.exists() else path
            if (
                candidate.exists()
                and candidate not in paths
                and self.has_direct_relevant_ads(candidate)
            ):
                paths.append(candidate)
        return paths

    def update(self, profile: Profile, collect_dir: Path, root_dir: Path) -> None:
        fresh = self._ads(collect_dir / "ads.relevant.json")
        pool_paths = [collect_dir.parent / "calibration_pool.json"]
        if profile.expected_country:
            pool_paths.append(
                root_dir
                / "calibration_pools"
                / f"{calibration_pool_name(profile.expected_country)}.json"
            )
        with self._lock:
            for pool_path in pool_paths:
                merged = merge_calibration_ads(fresh, self._ads(pool_path))
                _write_json(pool_path, merged)

    def has_relevant_ads(self, path: Path) -> bool:
        return any(is_relevant_ad(raw) for raw in self._ads(path))

    def has_direct_relevant_ads(self, path: Path) -> bool:
        return any(is_direct_calibration_target(raw) for raw in self._ads(path))

    @staticmethod
    def _ads(path: Path) -> list[dict[str, Any]]:
        payload = _load_json(path, default=[])
        if not isinstance(payload, list):
            return []
        return [raw for raw in payload if isinstance(raw, dict)]


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
