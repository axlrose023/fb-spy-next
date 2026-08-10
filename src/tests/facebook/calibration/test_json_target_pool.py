from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from app.facebook.calibration import JsonCalibrationTargetPool, persistent_target_pool
from app.facebook.profiles import Profile

pytestmark = pytest.mark.unit


class TargetLoader:
    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.options: dict[str, Any] = {}

    def __call__(
        self,
        ads_json_paths: list[Path],
        *,
        country: str | None,
        limit: int,
        excluded_urls: set[str],
        include_direct_offers: bool,
    ) -> list[Any]:
        self.paths = ads_json_paths
        self.options = {
            "country": country,
            "limit": limit,
            "excluded_urls": excluded_urls,
            "include_direct_offers": include_direct_offers,
        }
        return [object(), object()]


def relevant_offer(url: str) -> dict[str, Any]:
    return {"landing_full": url, "relevance": {"result": "relevant"}}


def write_ads(path: Path, ads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ads), encoding="utf-8")


def test_count_uses_selected_paths_country_and_quarantine(tmp_path: Path) -> None:
    collect_dir = tmp_path / "profiles" / "spain" / "collect"
    source = collect_dir.parent / "calibration_pool.json"
    write_ads(source, [relevant_offer("https://offer.example")])
    loader = TargetLoader()
    health_path: Path | None = None

    def quarantine(path: Path | None) -> set[str]:
        nonlocal health_path
        health_path = path
        return {"https://facebook.example/quarantined"}

    pool = JsonCalibrationTargetPool(loader, quarantine)
    profile = Profile(octo_profile_uuid="profile", expected_country="Spain")

    assert pool.count(profile, collect_dir, tmp_path) == 2
    assert loader.paths == [source]
    assert loader.options == {
        "country": "Spain",
        "limit": 10_000,
        "include_direct_offers": True,
        "excluded_urls": {"https://facebook.example/quarantined"},
    }
    assert health_path == collect_dir.parent / "calibration_target_health.json"


def test_count_fails_closed_when_loader_rejects_artifact(tmp_path: Path) -> None:
    collect_dir = tmp_path / "profiles" / "profile" / "collect"
    write_ads(
        collect_dir / "ads.relevant.json",
        [relevant_offer("https://offer.example")],
    )

    def fail(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise ValueError("malformed source")

    pool = JsonCalibrationTargetPool(fail, lambda _path: set())

    assert pool.count(Profile("profile", no_country_filter=True), collect_dir) == 0


def test_update_keeps_fresh_precedence_and_writes_profile_and_geo_pools(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    collect_dir = root / "profiles" / "spain" / "collect"
    fresh = relevant_offer("https://fresh.example")
    fresh["fb_ad_id"] = "same"
    previous = relevant_offer("https://previous.example")
    previous["fb_ad_id"] = "same"
    write_ads(collect_dir / "ads.relevant.json", [fresh])
    write_ads(collect_dir.parent / "calibration_pool.json", [previous])
    pool = JsonCalibrationTargetPool(lambda *_args, **_kwargs: [], lambda _path: set())

    pool.update(Profile("profile", expected_country="Spain"), collect_dir, root)

    profile_pool = json.loads(
        (collect_dir.parent / "calibration_pool.json").read_text(encoding="utf-8")
    )
    geo_pool = json.loads(
        (root / "calibration_pools" / "spain.json").read_text(encoding="utf-8")
    )
    assert profile_pool == [fresh]
    assert geo_pool == [fresh]


def test_configured_source_prefers_relevant_variant_and_ignores_malformed_json(
    tmp_path: Path,
) -> None:
    collect_dir = tmp_path / "profile" / "collect"
    configured = tmp_path / "fallback" / "ads.json"
    relevant_variant = configured.with_name("ads.relevant.json")
    write_ads(configured, [relevant_offer("https://fallback.example")])
    write_ads(relevant_variant, [relevant_offer("https://relevant.example")])
    malformed = collect_dir.parent / "calibration_pool.json"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_text("not-json", encoding="utf-8")
    pool = JsonCalibrationTargetPool(
        lambda *_args, **_kwargs: [],
        lambda _path: set(),
    )
    profile = Profile(
        "profile",
        calibration_ads_json=[str(configured)],
    )

    assert pool.source_paths(profile, collect_dir, tmp_path) == [relevant_variant]
    assert pool.has_relevant_ads(relevant_variant)
    assert not pool.has_relevant_ads(malformed)


def test_update_without_country_recovers_non_list_profile_pool(tmp_path: Path) -> None:
    root = tmp_path / "root"
    collect_dir = root / "profiles" / "profile" / "collect"
    write_ads(
        collect_dir / "ads.relevant.json",
        [relevant_offer("https://fresh.example")],
    )
    pool_path = collect_dir.parent / "calibration_pool.json"
    pool_path.write_text(json.dumps({"unexpected": "object"}), encoding="utf-8")
    pool = JsonCalibrationTargetPool(
        lambda *_args, **_kwargs: [],
        lambda _path: set(),
    )

    pool.update(Profile("profile"), collect_dir, root)

    assert json.loads(pool_path.read_text(encoding="utf-8")) == [
        relevant_offer("https://fresh.example")
    ]
    assert not (root / "calibration_pools").exists()


def test_directory_source_is_treated_as_unreadable_json(tmp_path: Path) -> None:
    pool = JsonCalibrationTargetPool(
        lambda *_args, **_kwargs: [],
        lambda _path: set(),
    )

    assert not pool.has_direct_relevant_ads(tmp_path)


def test_configured_variant_does_not_duplicate_fresh_run_source(tmp_path: Path) -> None:
    collect_dir = tmp_path / "profile" / "collect"
    fresh = collect_dir / "ads.relevant.json"
    write_ads(fresh, [relevant_offer("https://fresh.example")])
    pool = JsonCalibrationTargetPool(
        lambda *_args, **_kwargs: [],
        lambda _path: set(),
    )
    profile = Profile(
        "profile",
        calibration_ads_json=[str(collect_dir / "ads.json")],
    )

    assert pool.source_paths(profile, collect_dir, tmp_path) == [fresh]


def test_shared_lock_prevents_lost_geo_pool_updates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    first_dir = root / "profiles" / "first" / "collect"
    second_dir = root / "profiles" / "second" / "collect"
    write_ads(
        first_dir / "ads.relevant.json",
        [relevant_offer("https://first.example")],
    )
    write_ads(
        second_dir / "ads.relevant.json",
        [relevant_offer("https://second.example")],
    )
    lock = threading.Lock()
    pools = [
        JsonCalibrationTargetPool(
            lambda *_args, **_kwargs: [],
            lambda _path: set(),
            lock=lock,
        )
        for _ in range(2)
    ]
    profile = Profile("profile", expected_country="Spain")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(pool.update, profile, collect_dir, root)
            for pool, collect_dir in zip(pools, (first_dir, second_dir), strict=True)
        ]
        for future in futures:
            future.result()

    geo_ads = json.loads(
        (root / "calibration_pools" / "spain.json").read_text(encoding="utf-8")
    )
    assert {ad["landing_full"] for ad in geo_ads} == {
        "https://first.example",
        "https://second.example",
    }


def test_persistent_pool_wires_saved_targets_and_quarantine(tmp_path: Path) -> None:
    collect_dir = tmp_path / "profiles" / "spain" / "collect"
    post_url = "https://www.facebook.com/100/posts/200"
    write_ads(
        collect_dir.parent / "calibration_pool.json",
        [
            {
                "country": "Spain",
                "facebook_post_url": post_url,
                "relevance": {"result": "relevant"},
            }
        ],
    )
    health_path = collect_dir.parent / "calibration_target_health.json"
    health_path.write_text(
        json.dumps(
            {
                "version": 1,
                "targets": {
                    post_url: {"quarantined_until": "2099-01-01T00:00:00+00:00"}
                },
            }
        ),
        encoding="utf-8",
    )
    pool = persistent_target_pool()

    assert pool is persistent_target_pool()
    assert pool.count(Profile("profile", expected_country="Spain"), collect_dir) == 0
