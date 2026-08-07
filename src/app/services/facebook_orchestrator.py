"""Profile-level Facebook collector orchestrator.

This is intentionally a thin CLI layer over the existing runner and calibrator.
It keeps state in JSON files, runs one job per Octo profile at a time, and does
not require backend or frontend changes.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import json
import math
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services.facebook.calibration import (
    load_saved_facebook_targets_from_ads_json,
    quarantined_facebook_post_urls,
)
from app.services.facebook.health import (
    CalibrationDecision,
    CalibrationPolicy,
    MetricBaseline,
    RunMetrics,
    baseline_from_history,
    collect_run_metrics,
    evaluate_calibration_need,
    is_good_baseline_candidate,
    metrics_from_dict,
)
from app.settings import get_config

_PROFILES_FILE_LOCK = threading.Lock()
_POOL_FILE_LOCK = threading.Lock()
_ACTIVE_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen] = set()
_STOP_EVENT = threading.Event()
_RECOVERY_CALIBRATION_REASONS = {
    "zero_ads_repeated",
    "zero_relevant_ads",
}
_LOW_RELEVANCE_CALIBRATION_REASONS = {
    "one_relevant_ad",
    "proactive_quality_drop",
    "relevance_rate_below_minimum",
    "relevance_rate_too_low",
    "too_few_relevant_ads",
}


@dataclass
class ProfileConfig:
    octo_profile_uuid: str
    label: str = ""
    expected_country: str | None = None
    enabled: bool = True
    no_country_filter: bool = False
    calibration_ads_json: list[str] = field(default_factory=list)
    quality_guard: bool = False
    failed_recovery_calibration_passes: int = 1

    @property
    def display_name(self) -> str:
        return self.label or self.octo_profile_uuid[:8]

    @property
    def storage_name(self) -> str:
        slug = "".join(
            char.lower() if char.isascii() and char.isalnum() else "_"
            for char in self.display_name
        )
        slug = "_".join(part for part in slug.split("_") if part) or "profile"
        return f"{slug[:40]}_{self.octo_profile_uuid[:8]}"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProfileConfig:
        return cls(
            octo_profile_uuid=str(raw["octo_profile_uuid"]),
            label=str(raw.get("label") or ""),
            expected_country=raw.get("expected_country"),
            enabled=bool(raw.get("enabled", True)),
            no_country_filter=bool(raw.get("no_country_filter", False)),
            calibration_ads_json=[
                str(path) for path in raw.get("calibration_ads_json", [])
            ],
            quality_guard=bool(raw.get("quality_guard", False)),
            failed_recovery_calibration_passes=min(
                3,
                max(1, int(raw.get("failed_recovery_calibration_passes", 1))),
            ),
        )


@dataclass(frozen=True)
class CalibrationPlan:
    tier: str
    target_limit: int
    target_goal: int
    max_reactions: int
    max_follows: int
    max_comments: int
    min_interactions: int


@dataclass(frozen=True)
class RecoverySchedulePolicy:
    normal_rest_seconds: float
    burst_limit: int
    burst_rest_seconds: float
    infrastructure_retry_seconds: float


@dataclass(frozen=True)
class ProfileCycleSchedule:
    kind: str
    rest_seconds: float
    recovery_burst_count: int = 0
    recovery_attempt: int | None = None
    recovery_active: bool = False


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError(f"profile locked: {self.path}") from exc
        os.ftruncate(self.fd, 0)
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    @contextmanager
    def _process_lock(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"profiles": {}}

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

    def record_profile_run(
        self,
        profile: ProfileConfig,
        metrics: RunMetrics,
        decision: CalibrationDecision,
        *,
        calibration: dict[str, Any] | None = None,
        calibrations: list[dict[str, Any]] | None = None,
        policy: CalibrationPolicy,
        schedule_policy: RecoverySchedulePolicy | None = None,
        infrastructure_retry_required: bool = False,
    ) -> ProfileCycleSchedule:
        with self._lock, self._process_lock():
            state = self.load()
            profile_state = state.setdefault("profiles", {}).setdefault(
                profile.octo_profile_uuid,
                {
                    "octo_profile_uuid": profile.octo_profile_uuid,
                    "label": profile.label,
                    "expected_country": profile.expected_country,
                    "runs": [],
                    "calibrations": [],
                },
            )
            profile_state["label"] = profile.label
            profile_state["expected_country"] = profile.expected_country
            runs = profile_state.setdefault("runs", [])
            baseline_candidate = is_good_baseline_candidate(metrics, policy) and (
                decision.baseline.sample_count < policy.baseline_min_samples
                or decision.status == "healthy"
            )
            trusted_baseline = (
                profile.quality_guard
                and not decision.baseline.trusted
                and baseline_candidate
                and _is_healthy_relevance_result(metrics, policy)
            )
            runs.append(
                {
                    "at": utc_now(),
                    "run_dir": metrics.run_dir,
                    "baseline_candidate": baseline_candidate,
                    "trusted_baseline": trusted_baseline,
                    "metrics": metrics.to_dict(),
                    "decision": decision.to_dict(),
                }
            )
            del runs[:-100]
            calibration_records = list(calibrations or [])
            if calibration and not calibration_records:
                calibration_records.append(calibration)
            if calibration_records:
                stored_calibrations = profile_state.setdefault("calibrations", [])
                stored_calibrations.extend(calibration_records)
                del stored_calibrations[:-100]
            last_calibration = (
                calibration_records[-1] if calibration_records else calibration
            )
            schedule = _next_profile_schedule(
                previous_burst_count=_nonnegative_int(
                    profile_state.get("recovery_burst_count")
                ),
                previous_recovery_active=_profile_state_recovery_active(profile_state),
                metrics=metrics,
                decision=decision,
                calibration=last_calibration,
                infrastructure_retry_required=infrastructure_retry_required,
                policy=schedule_policy
                or RecoverySchedulePolicy(
                    normal_rest_seconds=0.0,
                    burst_limit=3,
                    burst_rest_seconds=0.0,
                    infrastructure_retry_seconds=300.0,
                ),
            )
            profile_state["recovery_burst_count"] = schedule.recovery_burst_count
            profile_state["last_schedule"] = asdict(schedule)
            baseline = _baseline_from_run_records(runs, policy)
            profile_state["baseline"] = baseline.to_dict()
            profile_state["updated_at"] = utc_now()
            self.save(state)
            return schedule

    def seed_baseline(
        self,
        profile_uuid: str,
        metrics: RunMetrics,
        *,
        label: str = "",
        expected_country: str | None = None,
        policy: CalibrationPolicy,
    ) -> MetricBaseline:
        with self._lock, self._process_lock():
            state = self.load()
            profile_state = state.setdefault("profiles", {}).setdefault(
                profile_uuid,
                {
                    "octo_profile_uuid": profile_uuid,
                    "label": label,
                    "expected_country": expected_country,
                    "runs": [],
                    "calibrations": [],
                },
            )
            runs = profile_state.setdefault("runs", [])
            runs.append(
                {
                    "at": utc_now(),
                    "run_dir": metrics.run_dir,
                    "seed_baseline": True,
                    "baseline_candidate": True,
                    "metrics": metrics.to_dict(),
                }
            )
            del runs[:-100]
            baseline = _baseline_from_run_records(runs, policy)
            profile_state["baseline"] = baseline.to_dict()
            profile_state["updated_at"] = utc_now()
            self.save(state)
            return baseline

    def profile_history(
        self, profile_uuid: str
    ) -> tuple[list[RunMetrics], MetricBaseline, list[str]]:
        with self._lock, self._process_lock():
            profile_state = self.load().get("profiles", {}).get(profile_uuid, {})
            runs = [
                metrics_from_dict(item["metrics"])
                for item in profile_state.get("runs", [])
                if isinstance(item.get("metrics"), dict)
                and not item.get("seed_baseline")
            ]
            baseline = MetricBaseline.from_dict(profile_state.get("baseline"))
            calibrations = [
                str(item.get("finished_at") or item.get("started_at") or item.get("at"))
                for item in profile_state.get("calibrations", [])
                if _calibration_was_effective(item)
                and (
                    item.get("finished_at") or item.get("started_at") or item.get("at")
                )
            ]
            return runs, baseline, calibrations

    def profile_calibration_attempts(self, profile_uuid: str) -> list[str]:
        with self._lock, self._process_lock():
            profile_state = self.load().get("profiles", {}).get(profile_uuid, {})
            return [
                str(item.get("finished_at") or item.get("started_at") or item.get("at"))
                for item in profile_state.get("calibrations", [])
                if item.get("finished_at") or item.get("started_at") or item.get("at")
            ]

    def profile_calibration_target_offset(self, profile_uuid: str) -> int:
        with self._lock, self._process_lock():
            profile_state = self.load().get("profiles", {}).get(profile_uuid, {})
            consumed = 0
            for item in profile_state.get("calibrations", []):
                summary = (
                    item.get("summary") if isinstance(item.get("summary"), dict) else {}
                )
                value = (
                    summary.get("visited")
                    or item.get("target_limit")
                    or item.get("target_goal")
                    or CalibrationPolicy().min_successful_calibration_targets
                )
                try:
                    consumed += max(1, int(value))
                except (TypeError, ValueError):
                    consumed += CalibrationPolicy().min_successful_calibration_targets
            return consumed

    def profile_last_run_at(self, profile_uuid: str) -> str | None:
        with self._lock, self._process_lock():
            profile_state = self.load().get("profiles", {}).get(profile_uuid, {})
            for item in reversed(profile_state.get("runs", [])):
                if item.get("seed_baseline"):
                    continue
                value = item.get("at")
                if not value and isinstance(item.get("metrics"), dict):
                    value = item["metrics"].get("finished_at")
                if value:
                    return str(value)
            return None

    def profile_recovery_burst_count(self, profile_uuid: str) -> int:
        with self._lock, self._process_lock():
            profile_state = self.load().get("profiles", {}).get(profile_uuid, {})
            return _nonnegative_int(profile_state.get("recovery_burst_count"))

    def profile_recovery_evaluation_active(self, profile_uuid: str) -> bool:
        with self._lock, self._process_lock():
            profile_state = self.load().get("profiles", {}).get(profile_uuid, {})
            return _profile_state_recovery_active(profile_state)

    def profile_resume_schedule(
        self,
        profile_uuid: str,
        *,
        default_rest_seconds: float,
    ) -> ProfileCycleSchedule:
        with self._lock, self._process_lock():
            profile_state = self.load().get("profiles", {}).get(profile_uuid, {})
            raw = profile_state.get("last_schedule")
            if not isinstance(raw, dict):
                return ProfileCycleSchedule(
                    kind="normal",
                    rest_seconds=max(0.0, default_rest_seconds),
                    recovery_burst_count=_nonnegative_int(
                        profile_state.get("recovery_burst_count")
                    ),
                )
            try:
                rest_seconds = max(0.0, float(raw.get("rest_seconds", 0.0)))
            except (TypeError, ValueError):
                rest_seconds = max(0.0, default_rest_seconds)
            recovery_attempt = raw.get("recovery_attempt")
            return ProfileCycleSchedule(
                kind=str(raw.get("kind") or "normal"),
                rest_seconds=rest_seconds,
                recovery_burst_count=_nonnegative_int(
                    raw.get(
                        "recovery_burst_count",
                        profile_state.get("recovery_burst_count"),
                    )
                ),
                recovery_attempt=(
                    _nonnegative_int(recovery_attempt)
                    if recovery_attempt is not None
                    else None
                ),
                recovery_active=bool(
                    raw.get("recovery_active")
                    or raw.get("kind") in {"recovery_burst", "recovery_burst_rest"}
                ),
            )


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _profile_state_recovery_active(profile_state: dict[str, Any]) -> bool:
    if _nonnegative_int(profile_state.get("recovery_burst_count")) > 0:
        return True
    schedule = profile_state.get("last_schedule")
    if not isinstance(schedule, dict):
        return False
    return bool(
        schedule.get("recovery_active")
        or schedule.get("kind") in {"recovery_burst", "recovery_burst_rest"}
    )


def _next_profile_schedule(
    *,
    previous_burst_count: int,
    metrics: RunMetrics,
    decision: CalibrationDecision,
    calibration: dict[str, Any] | None,
    policy: RecoverySchedulePolicy,
    previous_recovery_active: bool = False,
    infrastructure_retry_required: bool = False,
) -> ProfileCycleSchedule:
    burst_count = max(0, previous_burst_count)
    recovery_active = previous_recovery_active or burst_count > 0
    normal_rest = max(0.0, policy.normal_rest_seconds)
    retry_rest = max(0.0, policy.infrastructure_retry_seconds)

    blocked_technical_stop = (
        calibration is None
        and decision.status != "healthy"
        and any(
            blocker
            in {
                "collector_stop_reason_resolve_timeout",
                "collector_stop_reason_scroll_failed",
                "collector_stop_reason_video_timeout",
            }
            for blocker in decision.blockers
        )
    )
    collector_failed = metrics.return_code not in {
        None,
        0,
    } and metrics.stop_reason not in {"facebook_login_required", "interrupted"}
    if (
        infrastructure_retry_required
        or collector_failed
        or blocked_technical_stop
        or metrics.stop_reason in {"octo_proxy_error", "octo_start_error"}
    ):
        return ProfileCycleSchedule(
            kind="infrastructure_retry",
            rest_seconds=retry_rest,
            recovery_burst_count=burst_count,
            recovery_active=recovery_active,
        )

    if calibration:
        summary = (
            calibration.get("summary")
            if isinstance(calibration.get("summary"), dict)
            else {}
        )
        status = str(summary.get("status") or "")
        if status == "infrastructure_error" or summary.get("infrastructure_error"):
            return ProfileCycleSchedule(
                kind="infrastructure_retry",
                rest_seconds=retry_rest,
                recovery_burst_count=burst_count,
                recovery_active=recovery_active,
            )
        if status not in {"completed", "dry_run"}:
            return ProfileCycleSchedule(
                kind="calibration_retry",
                rest_seconds=retry_rest,
                recovery_burst_count=burst_count,
                recovery_active=recovery_active,
            )
        if _is_recovery_calibration_decision(decision):
            attempt = burst_count + 1
            if attempt >= max(1, policy.burst_limit):
                return ProfileCycleSchedule(
                    kind="recovery_burst_rest",
                    rest_seconds=normal_rest,
                    recovery_burst_count=0,
                    recovery_attempt=attempt,
                    recovery_active=True,
                )
            return ProfileCycleSchedule(
                kind="recovery_burst",
                rest_seconds=max(0.0, policy.burst_rest_seconds),
                recovery_burst_count=attempt,
                recovery_attempt=attempt,
                recovery_active=True,
            )
        return ProfileCycleSchedule(
            kind="normal",
            rest_seconds=normal_rest,
            recovery_burst_count=0,
        )

    if decision.status == "healthy":
        burst_count = 0
        recovery_active = False
    return ProfileCycleSchedule(
        kind="normal",
        rest_seconds=normal_rest,
        recovery_burst_count=burst_count,
        recovery_active=recovery_active,
    )


def _is_recovery_calibration_decision(decision: CalibrationDecision) -> bool:
    return bool(set(decision.reasons) - {"periodic_account_maintenance"})


def _is_healthy_relevance_result(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    return bool(
        metrics.target_source == "relevance"
        and metrics.relevance_known
        and metrics.relevance_coverage is not None
        and metrics.relevance_coverage >= policy.min_relevance_coverage
        and metrics.relevant_rate is not None
        and metrics.relevant_rate >= policy.minimum_healthy_relevant_rate
        and int(metrics.relevant_ads or 0) >= policy.minimum_healthy_relevant_ads
    )


def _baseline_from_run_records(
    records: list[dict[str, Any]],
    policy: CalibrationPolicy,
) -> MetricBaseline:
    by_run_dir: dict[str, RunMetrics] = {}
    for item in records:
        raw_metrics = item.get("metrics")
        if not isinstance(raw_metrics, dict):
            continue
        metrics = metrics_from_dict(raw_metrics)
        explicitly_eligible = item.get("seed_baseline") or item.get(
            "baseline_candidate"
        )
        legacy_record = "baseline_candidate" not in item
        if not explicitly_eligible and not (
            legacy_record and is_good_baseline_candidate(metrics, policy)
        ):
            continue
        by_run_dir.pop(metrics.run_dir, None)
        by_run_dir[metrics.run_dir] = metrics
    baseline = MetricBaseline.from_good_runs(
        list(by_run_dir.values()),
        max_samples=policy.baseline_window,
        min_healthy_relevant_rate=policy.minimum_healthy_relevant_rate,
        min_healthy_relevant_ads=policy.minimum_healthy_relevant_ads,
    )
    trusted_dirs = {
        str(item.get("run_dir") or "")
        for item in records
        if item.get("seed_baseline") or item.get("trusted_baseline")
    }
    trusted = bool(trusted_dirs.intersection(baseline.source_run_dirs))
    return replace(baseline, trusted=trusted)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "run":
        signal.signal(signal.SIGINT, _request_orchestrator_stop)
        signal.signal(signal.SIGTERM, _request_orchestrator_stop)
        return _run(args)
    if args.command == "evaluate":
        return _evaluate(args)
    if args.command == "seed-baseline":
        return _seed_baseline(args)
    if args.command == "discover-active":
        return _discover_active(args)
    if args.command == "discover-octo":
        return _discover_public(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run profile collect/evaluate/calibrate cycles.")
    _add_common_paths(run)
    run.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    run.add_argument("--max-parallel", type=int, default=2)
    run.add_argument("--loop", action="store_true")
    run.add_argument("--cycle-sleep", type=float, default=60.0)
    run.add_argument(
        "--profile-rest-minutes",
        type=float,
        default=0.0,
        help=(
            "Minimum rest after a profile finishes collection and optional "
            "calibration. The larger of this value and --cycle-sleep is used."
        ),
    )
    run.add_argument(
        "--recovery-burst-cycles",
        type=int,
        default=3,
        help=(
            "Number of collect/calibrate recovery cycles run without the normal "
            "profile rest before applying backoff."
        ),
    )
    run.add_argument(
        "--recovery-burst-rest-minutes",
        type=float,
        default=0.0,
        help="Delay before the next validation collection inside a recovery burst.",
    )
    run.add_argument(
        "--infrastructure-retry-minutes",
        type=float,
        default=5.0,
        help="Retry delay after Octo, proxy, or calibration infrastructure errors.",
    )
    run.add_argument("--discovery-interval", type=float, default=300.0)
    run.add_argument("--max-cycles", type=int, default=0, help=argparse.SUPPRESS)
    run.add_argument("--collect-minutes", type=float, default=15.0)
    run.add_argument("--collect-timeout-grace", type=float, default=180.0)
    run.add_argument("--collect-scrolls", type=int, default=10000)
    run.add_argument("--resolve-max", type=int, default=200)
    run.add_argument("--scroll-px", type=int, default=520)
    run.add_argument("--max-ads-per-view", type=int, default=1)
    run.add_argument("--landing-archive-timeout", type=float, default=12.0)
    run.add_argument("--landing-archive-max-resources", type=int, default=80)
    run.add_argument("--video-max-seconds", type=float, default=10.0)
    run.add_argument("--no-video-recording", action="store_true")
    run.add_argument("--no-landing-archives", action="store_true")
    run.add_argument(
        "--interest-safe-collection",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Passively scan the feed, classify cards first, and allow active "
            "browser actions only for relevance-gated ads."
        ),
    )
    run.add_argument(
        "--relevant-enrichment",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Capture video and landing artifacts only for prefiltered ads.",
    )
    run.add_argument(
        "--isolated-hold-resolution",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Resolve uncertain passive CTA URLs in a cookie-free context before "
            "allowing any authenticated profile action."
        ),
    )
    run.add_argument("--isolated-resolution-timeout", type=float, default=900.0)
    run.add_argument("--enrichment-timeout", type=float, default=1200.0)
    run.add_argument("--octo-host", default="")
    run.add_argument("--octo-port", type=int, default=0)
    run.add_argument(
        "--octo-headless",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    run.add_argument("--debug", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--calibration-limit", type=int, default=20)
    run.add_argument("--calibration-target-goal", type=int, default=10)
    run.add_argument(
        "--calibration-low-relevance-target-goal",
        type=int,
        default=30,
    )
    run.add_argument(
        "--calibration-recovery-target-goal",
        type=int,
        default=40,
    )
    run.add_argument(
        "--calibration-recovery-target-limit",
        type=int,
        default=50,
    )
    run.add_argument("--calibration-timeout-grace", type=float, default=180.0)
    run.add_argument("--calibration-view-seconds", type=float, default=45.0)
    run.add_argument("--calibration-pause", type=float, default=2.0)
    run.add_argument("--calibration-locate-timeout", type=float, default=12.0)
    run.add_argument("--calibration-page-timeout", type=float, default=45.0)
    run.add_argument(
        "--calibration-visit-landing",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-landing-view-seconds", type=float, default=45.0)
    run.add_argument("--calibration-landing-timeout", type=float, default=20.0)
    run.add_argument(
        "--calibration-offer-funnel",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument(
        "--calibration-direct-offer-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-session-minutes", type=float, default=15.0)
    run.add_argument(
        "--calibration-repeat-targets-until-deadline",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-funnel-target-goal", type=int, default=3)
    run.add_argument("--calibration-prelander-max-scrolls", type=int, default=12)
    run.add_argument("--calibration-quiz-max-questions", type=int, default=10)
    run.add_argument(
        "--calibration-offer-submit-mode",
        choices=("disabled", "fill_only", "allowlisted"),
        default="disabled",
    )
    run.add_argument(
        "--calibration-offer-submit-allow-domain",
        action="append",
        default=[
            value.strip()
            for value in os.getenv(
                "FACEBOOK_CALIBRATION_OFFER_SUBMIT_ALLOW_DOMAINS",
                "",
            ).split(",")
            if value.strip()
        ],
    )
    run.add_argument(
        "--calibration-offer-identity-json",
        default=os.getenv("FACEBOOK_CALIBRATION_OFFER_IDENTITY_JSON", ""),
    )
    run.add_argument("--calibration-offer-success-wait-seconds", type=float, default=20.0)
    run.add_argument("--calibration-max-retained-offer-tabs", type=int, default=6)
    run.add_argument("--min-calibration-targets", type=int, default=2)
    run.add_argument("--calibration-cooldown-hours", type=float, default=1.0)
    run.add_argument(
        "--soft-drop-calibration-windows",
        type=int,
        default=3,
    )
    run.add_argument("--watch-drop-ratio", type=float, default=0.70)
    run.add_argument("--immediate-drop-ratio", type=float, default=0.70)
    run.add_argument(
        "--minimum-healthy-relevant-rate",
        type=float,
        default=0.75,
    )
    run.add_argument(
        "--minimum-healthy-relevant-ads",
        type=int,
        default=15,
    )
    run.add_argument("--zero-ads-windows", type=int, default=2)
    run.add_argument("--absolute-low-ads-windows", type=int, default=2)
    run.add_argument("--absolute-low-ads-per-hour", type=float, default=12.0)
    run.add_argument(
        "--zero-ads-calibration-cooldown-minutes",
        type=float,
        default=30.0,
    )
    run.add_argument("--zero-ads-calibration-burst-limit", type=int, default=8)
    run.add_argument(
        "--zero-ads-calibration-backoff-hours",
        type=float,
        default=2.0,
    )
    run.add_argument("--calibration-retry-cooldown-hours", type=float, default=0.5)
    run.add_argument(
        "--maintenance-calibration-hours",
        type=float,
        default=6.0,
    )
    run.add_argument(
        "--maintenance-min-valid-windows",
        type=int,
        default=3,
    )
    run.add_argument("--max-calibrations-per-24h", type=int, default=24)
    run.add_argument("--calibration-reaction-rate", type=float, default=0.65)
    run.add_argument("--calibration-follow-rate", type=float, default=0.20)
    run.add_argument("--calibration-comment-every", type=int, default=0)
    run.add_argument("--calibration-max-reactions", type=int, default=6)
    run.add_argument("--calibration-max-follows", type=int, default=2)
    run.add_argument("--calibration-max-comments", type=int, default=0)
    run.add_argument("--calibration-min-interactions", type=int, default=1)
    run.add_argument("--calibration-comment-template", action="append", default=[])
    run.add_argument(
        "--classify-relevance",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    run.add_argument("--relevance-timeout", type=float, default=900.0)
    run.add_argument(
        "--import-backend",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Import each completed classified run into the application database.",
    )
    run.add_argument("--backend-import-timeout", type=float, default=300.0)
    run.add_argument("--discover-octo-profiles", action="store_true")
    run.add_argument("--octo-api-token", default="")
    run.add_argument("--octo-search-tags", default="")
    run.add_argument("--enable-discovered", action="store_true")

    evaluate = sub.add_parser("evaluate", help="Evaluate one existing collect run.")
    _add_common_paths(evaluate)
    evaluate.add_argument("--run-dir", required=True)
    evaluate.add_argument("--profile-uuid", default="")
    evaluate.add_argument("--expected-country", default="")
    evaluate.add_argument("--return-code", type=int)
    evaluate.add_argument("--default-elapsed-seconds", type=float)
    evaluate.add_argument("--default-scrolls", type=int)
    evaluate.add_argument("--calibration-targets", type=int)

    seed = sub.add_parser(
        "seed-baseline", help="Record an existing good run as baseline."
    )
    _add_common_paths(seed)
    seed.add_argument("--run-dir", required=True)
    seed.add_argument("--profile-uuid", required=True)
    seed.add_argument("--label", default="")
    seed.add_argument("--expected-country", default="")
    seed.add_argument("--default-elapsed-seconds", type=float)
    seed.add_argument("--default-scrolls", type=int)

    discover = sub.add_parser(
        "discover-active", help="Merge active Octo profiles into profiles JSON."
    )
    discover.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    discover.add_argument("--octo-host", default="127.0.0.1")
    discover.add_argument("--octo-port", type=int, default=58888)
    discover.add_argument("--enable-new", action="store_true")

    discover_public = sub.add_parser(
        "discover-octo", help="Merge Octo Public API profiles into profiles JSON."
    )
    discover_public.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    discover_public.add_argument("--octo-api-token", default="")
    discover_public.add_argument("--octo-search-tags", default="")
    discover_public.add_argument("--enable-new", action="store_true")
    return parser


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root-dir", default="storage/facebook/orchestrator")
    parser.add_argument(
        "--state-json", default="storage/facebook/orchestrator/state.json"
    )


def _run(args) -> int:
    _STOP_EVENT.clear()
    store = StateStore(Path(args.state_json))
    root_dir = Path(args.root_dir)
    policy = _calibration_policy(args)
    if args.max_parallel < 1:
        raise ValueError("--max-parallel must be at least 1")
    if args.profile_rest_minutes < 0:
        raise ValueError("--profile-rest-minutes cannot be negative")
    if args.recovery_burst_cycles < 1:
        raise ValueError("--recovery-burst-cycles must be at least 1")
    if args.recovery_burst_rest_minutes < 0:
        raise ValueError("--recovery-burst-rest-minutes cannot be negative")
    if args.infrastructure_retry_minutes < 0:
        raise ValueError("--infrastructure-retry-minutes cannot be negative")
    if args.calibration_limit < 1:
        raise ValueError("--calibration-limit must be at least 1")
    if args.calibration_target_goal < 1:
        raise ValueError("--calibration-target-goal must be at least 1")
    if args.calibration_low_relevance_target_goal < 1:
        raise ValueError("--calibration-low-relevance-target-goal must be at least 1")
    if args.calibration_recovery_target_goal < 1:
        raise ValueError("--calibration-recovery-target-goal must be at least 1")
    if args.calibration_recovery_target_limit < args.calibration_recovery_target_goal:
        raise ValueError(
            "--calibration-recovery-target-limit must be at least "
            "--calibration-recovery-target-goal"
        )
    if args.calibration_page_timeout <= 0:
        raise ValueError("--calibration-page-timeout must be greater than 0")
    if args.calibration_landing_view_seconds < 0:
        raise ValueError("--calibration-landing-view-seconds cannot be negative")
    if args.calibration_landing_timeout <= 0:
        raise ValueError("--calibration-landing-timeout must be greater than 0")
    if args.calibration_session_minutes < 0:
        raise ValueError("--calibration-session-minutes cannot be negative")
    if args.calibration_funnel_target_goal < 1:
        raise ValueError("--calibration-funnel-target-goal must be at least 1")
    if args.calibration_prelander_max_scrolls < 0:
        raise ValueError("--calibration-prelander-max-scrolls cannot be negative")
    if args.calibration_quiz_max_questions < 0:
        raise ValueError("--calibration-quiz-max-questions cannot be negative")
    if args.calibration_offer_success_wait_seconds < 0:
        raise ValueError("--calibration-offer-success-wait-seconds cannot be negative")
    if args.calibration_max_retained_offer_tabs < 1:
        raise ValueError("--calibration-max-retained-offer-tabs must be at least 1")
    if args.calibration_offer_submit_mode == "allowlisted":
        if not args.calibration_offer_submit_allow_domain:
            raise ValueError(
                "allowlisted offer submit requires "
                "--calibration-offer-submit-allow-domain"
            )
        if not args.calibration_offer_identity_json:
            raise ValueError(
                "allowlisted offer submit requires "
                "--calibration-offer-identity-json"
            )
    if args.min_calibration_targets < 1:
        raise ValueError("--min-calibration-targets must be at least 1")
    _discover_profiles(args, fail_fast=True)
    if not args.loop:
        return _run_once(args, store, policy, root_dir)
    return _run_continuously(args, store, policy, root_dir)


def _calibration_policy(args) -> CalibrationPolicy:
    if args.calibration_cooldown_hours < 0:
        raise ValueError("--calibration-cooldown-hours cannot be negative")
    if args.soft_drop_calibration_windows < 2:
        raise ValueError("--soft-drop-calibration-windows must be at least 2")
    if not 0 < args.watch_drop_ratio <= 1:
        raise ValueError("--watch-drop-ratio must be greater than 0 and at most 1")
    if not 0 < args.immediate_drop_ratio <= 1:
        raise ValueError("--immediate-drop-ratio must be greater than 0 and at most 1")
    if not 0 < args.minimum_healthy_relevant_rate <= 1:
        raise ValueError(
            "--minimum-healthy-relevant-rate must be greater than 0 and at most 1"
        )
    if args.minimum_healthy_relevant_ads < 1:
        raise ValueError("--minimum-healthy-relevant-ads must be at least 1")
    if args.zero_ads_windows < 1:
        raise ValueError("--zero-ads-windows must be at least 1")
    if args.absolute_low_ads_windows < 1:
        raise ValueError("--absolute-low-ads-windows must be at least 1")
    if args.absolute_low_ads_per_hour < 0:
        raise ValueError("--absolute-low-ads-per-hour cannot be negative")
    if args.zero_ads_calibration_cooldown_minutes < 0:
        raise ValueError("--zero-ads-calibration-cooldown-minutes cannot be negative")
    if args.zero_ads_calibration_burst_limit < 1:
        raise ValueError("--zero-ads-calibration-burst-limit must be at least 1")
    if args.zero_ads_calibration_backoff_hours < 0:
        raise ValueError("--zero-ads-calibration-backoff-hours cannot be negative")
    if args.calibration_retry_cooldown_hours < 0:
        raise ValueError("--calibration-retry-cooldown-hours cannot be negative")
    if args.maintenance_calibration_hours < 0:
        raise ValueError("--maintenance-calibration-hours cannot be negative")
    if args.maintenance_min_valid_windows < 1:
        raise ValueError("--maintenance-min-valid-windows must be at least 1")
    if args.max_calibrations_per_24h < 1:
        raise ValueError("--max-calibrations-per-24h must be at least 1")
    return replace(
        CalibrationPolicy(),
        zero_ads_windows=args.zero_ads_windows,
        absolute_low_ads_windows=args.absolute_low_ads_windows,
        absolute_low_ads_per_hour=args.absolute_low_ads_per_hour,
        soft_drop_calibration_windows=args.soft_drop_calibration_windows,
        watch_drop_ratio=args.watch_drop_ratio,
        immediate_drop_ratio=args.immediate_drop_ratio,
        minimum_healthy_relevant_rate=args.minimum_healthy_relevant_rate,
        minimum_healthy_relevant_ads=args.minimum_healthy_relevant_ads,
        calibration_cooldown_seconds=args.calibration_cooldown_hours * 60 * 60,
        zero_ads_calibration_cooldown_seconds=(
            args.zero_ads_calibration_cooldown_minutes * 60
        ),
        zero_ads_calibration_burst_limit=args.zero_ads_calibration_burst_limit,
        zero_ads_calibration_backoff_seconds=(
            args.zero_ads_calibration_backoff_hours * 60 * 60
        ),
        calibration_retry_cooldown_seconds=(
            args.calibration_retry_cooldown_hours * 60 * 60
        ),
        maintenance_calibration_interval_seconds=(
            args.maintenance_calibration_hours * 60 * 60
        ),
        maintenance_min_valid_windows=args.maintenance_min_valid_windows,
        max_calibrations_per_24h=args.max_calibrations_per_24h,
        min_calibration_targets=args.min_calibration_targets,
        min_successful_calibration_targets=args.min_calibration_targets,
    )


def _run_once(
    args, store: StateStore, policy: CalibrationPolicy, root_dir: Path
) -> int:
    enabled_profiles = _enabled_profiles(args)
    if not enabled_profiles:
        print("No enabled profiles.", flush=True)
        return 1
    failed = False
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.max_parallel
    ) as executor:
        futures = [
            executor.submit(_run_profile_cycle, profile, args, store, policy, root_dir)
            for profile in enabled_profiles
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                failed = True
                print(f"[orchestrator] profile cycle failed: {exc!r}", flush=True)
    if _STOP_EVENT.is_set():
        return 130
    return 1 if failed else 0


def _run_continuously(
    args,
    store: StateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> int:
    """Schedule each profile independently without a global cycle barrier."""
    next_due: dict[str, float] = {}
    running: dict[str, concurrent.futures.Future] = {}
    profiles: dict[str, ProfileConfig] = {}
    next_discovery = 0.0
    completed_cycles = 0
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=args.max_parallel)
    try:
        while not _STOP_EVENT.is_set():
            now = time.monotonic()
            if now >= next_discovery:
                try:
                    _discover_profiles(args, fail_fast=False)
                    profiles = {
                        profile.octo_profile_uuid: profile
                        for profile in _enabled_profiles(args)
                    }
                    for uuid in profiles:
                        if uuid in next_due:
                            continue
                        schedule = store.profile_resume_schedule(
                            uuid,
                            default_rest_seconds=_profile_rest_seconds(args),
                        )
                        remaining_rest = _remaining_profile_rest_seconds(
                            store.profile_last_run_at(uuid),
                            schedule.rest_seconds,
                        )
                        next_due[uuid] = now + remaining_rest
                        if remaining_rest > 0:
                            print(
                                f"[{profiles[uuid].display_name}] resume "
                                f"schedule={schedule.kind} rest="
                                f"{remaining_rest / 60:.1f}m",
                                flush=True,
                            )
                finally:
                    next_discovery = now + max(5.0, args.discovery_interval)

            for uuid, future in list(running.items()):
                if not future.done():
                    continue
                del running[uuid]
                schedule = ProfileCycleSchedule(
                    kind="normal",
                    rest_seconds=_profile_rest_seconds(args),
                )
                try:
                    result = future.result()
                    if isinstance(result, ProfileCycleSchedule):
                        schedule = result
                except Exception as exc:
                    schedule = ProfileCycleSchedule(
                        kind="infrastructure_retry",
                        rest_seconds=_profile_schedule_policy(
                            args
                        ).infrastructure_retry_seconds,
                    )
                    print(
                        f"[orchestrator] profile {uuid[:8]} cycle failed: {exc!r}",
                        flush=True,
                    )
                next_due[uuid] = time.monotonic() + schedule.rest_seconds
                profile = profiles.get(uuid)
                if profile:
                    _log_profile_schedule(
                        profile,
                        schedule,
                        burst_limit=args.recovery_burst_cycles,
                    )
                completed_cycles += 1
                if args.max_cycles > 0 and completed_cycles >= args.max_cycles:
                    return 0

            available = args.max_parallel - len(running)
            due_profiles = sorted(
                (
                    profile
                    for uuid, profile in profiles.items()
                    if uuid not in running and next_due.get(uuid, 0.0) <= now
                ),
                key=lambda profile: next_due.get(profile.octo_profile_uuid, 0.0),
            )
            for profile in due_profiles[:available]:
                uuid = profile.octo_profile_uuid
                running[uuid] = executor.submit(
                    _run_profile_cycle,
                    profile,
                    args,
                    store,
                    policy,
                    root_dir,
                )

            if not profiles and not running:
                print(
                    "[orchestrator] no enabled profiles; waiting for discovery",
                    flush=True,
                )
            time.sleep(1.0)
        print("[orchestrator] stopping; waiting for active profile jobs", flush=True)
        return 130
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def _enabled_profiles(args) -> list[ProfileConfig]:
    return [
        profile
        for profile in _load_profiles(Path(args.profiles_json))
        if profile.enabled
    ]


def _profile_rest_seconds(args) -> float:
    return max(
        0.0,
        float(args.cycle_sleep),
        float(args.profile_rest_minutes) * 60.0,
    )


def _profile_schedule_policy(args) -> RecoverySchedulePolicy:
    return RecoverySchedulePolicy(
        normal_rest_seconds=_profile_rest_seconds(args),
        burst_limit=max(1, int(args.recovery_burst_cycles)),
        burst_rest_seconds=max(
            0.0,
            float(args.recovery_burst_rest_minutes) * 60.0,
        ),
        infrastructure_retry_seconds=max(
            0.0,
            float(args.infrastructure_retry_minutes) * 60.0,
        ),
    )


def _profile_evaluation_policy(
    policy: CalibrationPolicy,
    *,
    recovery_active: bool,
    quality_guard: bool = False,
) -> CalibrationPolicy:
    overrides: dict[str, Any] = {
        # Recovery bursts below provide the bounded backoff for this orchestrator.
        "zero_ads_calibration_burst_limit": max(
            policy.zero_ads_calibration_burst_limit,
            policy.max_calibrations_per_24h + 1,
        ),
        "proactive_quality_drop_enabled": quality_guard,
    }
    if recovery_active:
        overrides.update(
            calibration_cooldown_seconds=0.0,
            zero_ads_calibration_cooldown_seconds=0.0,
            calibration_retry_cooldown_seconds=0.0,
        )
    return replace(policy, **overrides)


def _log_profile_schedule(
    profile: ProfileConfig,
    schedule: ProfileCycleSchedule,
    *,
    burst_limit: int,
) -> None:
    if schedule.kind == "recovery_burst":
        delay = (
            "immediately"
            if schedule.rest_seconds <= 0
            else f"in {schedule.rest_seconds / 60:.1f}m"
        )
        print(
            f"[{profile.display_name}] recovery="
            f"{schedule.recovery_attempt}/{burst_limit}; "
            f"validation collect {delay}",
            flush=True,
        )
        return
    print(
        f"[{profile.display_name}] schedule={schedule.kind} "
        f"rest={schedule.rest_seconds / 60:.1f}m",
        flush=True,
    )


def _remaining_profile_rest_seconds(
    last_run_at: str | None,
    rest_seconds: float,
    *,
    now: datetime | None = None,
) -> float:
    if not last_run_at or rest_seconds <= 0:
        return 0.0
    try:
        parsed = datetime.fromisoformat(last_run_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    elapsed = max(
        0.0,
        ((now or datetime.now(UTC)) - parsed.astimezone(UTC)).total_seconds(),
    )
    return max(0.0, rest_seconds - elapsed)


def _discover_profiles(args, *, fail_fast: bool) -> None:
    if not args.discover_octo_profiles:
        return
    config = get_config()
    token = (
        args.octo_api_token
        or os.environ.get("OCTO_API_TOKEN", "")
        or config.facebook.octo_api_token
    )
    search_tags = args.octo_search_tags or config.facebook.octo_search_tags
    if not token:
        print(
            "[orchestrator] Octo Public API discovery skipped: token is not "
            "configured; using profiles.json",
            flush=True,
        )
        return
    try:
        added = _merge_public_profiles(
            Path(args.profiles_json),
            token=token,
            search_tags=search_tags,
            enable_new=args.enable_discovered,
        )
        if added:
            print(f"[orchestrator] discovered {added} new Octo profile(s)", flush=True)
    except Exception as exc:
        if fail_fast:
            raise
        print(f"[orchestrator] Octo discovery failed: {exc!r}", flush=True)


def _run_profile_cycle(
    profile: ProfileConfig,
    args,
    store: StateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> ProfileCycleSchedule:
    with _profile_cycle_guard(profile, args, root_dir):
        return _run_profile_cycle_locked(profile, args, store, policy, root_dir)


@contextmanager
def _profile_cycle_guard(profile: ProfileConfig, args, root_dir: Path):
    lock_path = root_dir / "locks" / f"{profile.octo_profile_uuid}.lock"
    with FileLock(lock_path):
        try:
            yield
        finally:
            if not args.dry_run:
                _stop_octo_profile(profile, args)


def _run_profile_cycle_locked(
    profile: ProfileConfig,
    args,
    store: StateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> ProfileCycleSchedule:
    cycle_at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    profile_root = root_dir / "profiles" / profile.storage_name
    collect_dir = profile_root / f"collect_{cycle_at}"
    collect_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{profile.display_name}] collect -> {collect_dir}", flush=True)
    collect_code = 0
    if not args.dry_run:
        collect_code = _run_command(
            _collector_command(profile, args, collect_dir),
            collect_dir / "runner.log",
            timeout_seconds=args.collect_minutes * 60 + args.collect_timeout_grace,
        )
    interest_safety_code: int | None = None
    if collect_code == 0 and args.interest_safe_collection and not args.dry_run:
        safety_violations = _interest_safe_collection_violations(collect_dir)
        interest_safety_code = 4 if safety_violations else 0
        _write_json(collect_dir / "interest_safety.json", {
            "status": "violation" if safety_violations else "passed",
            "violations": safety_violations,
        })
        if safety_violations:
            print(
                f"[{profile.display_name}] interest-safety invariant failed: "
                f"{','.join(safety_violations)}",
                flush=True,
            )
    prefilter_code: int | None = None
    isolated_resolution_code: int | None = None
    gate_resolution_code: int | None = None
    enrichment_code: int | None = None
    relevance_code: int | None = None
    relevance_enabled = _relevance_classification_enabled(args)
    if (
        collect_code == 0
        and interest_safety_code in {None, 0}
        and not args.dry_run
        and not _STOP_EVENT.is_set()
        and relevance_enabled
        and (collect_dir / "ads.json").exists()
    ):
        if args.interest_safe_collection:
            prefilter_code = _run_command(
                _relevance_classifier_command(collect_dir, stage="prefilter"),
                collect_dir / "prefilter.log",
                timeout_seconds=args.relevance_timeout,
            )
            if prefilter_code == 0 and not _STOP_EVENT.is_set():
                enrichment_source = collect_dir / "ads.prefilter.json"
                if args.isolated_hold_resolution:
                    isolated_resolution_code = _run_command(
                        _isolated_landing_resolver_command(
                            profile,
                            args,
                            collect_dir,
                        ),
                        collect_dir / "isolated_resolution.log",
                        timeout_seconds=args.isolated_resolution_timeout,
                    )
                    if (
                        isolated_resolution_code == 0
                        and not _STOP_EVENT.is_set()
                    ):
                        gate_resolution_code = _run_command(
                            _relevance_classifier_command(
                                collect_dir,
                                stage="resolve-holds",
                                source=collect_dir / "ads.isolated.json",
                            ),
                            collect_dir / "gate_resolution.log",
                            timeout_seconds=args.relevance_timeout,
                        )
                        if gate_resolution_code == 0:
                            enrichment_source = collect_dir / "ads.gated.json"
                else:
                    isolated_resolution_code = 0
                    gate_resolution_code = 0
                if args.relevant_enrichment:
                    if (
                        isolated_resolution_code in {None, 0}
                        and gate_resolution_code in {None, 0}
                        and not _STOP_EVENT.is_set()
                    ):
                        enrichment_code = _run_command(
                            _relevant_enricher_command(
                                profile,
                                args,
                                collect_dir,
                                source=enrichment_source,
                            ),
                            collect_dir / "enrichment.log",
                            timeout_seconds=args.enrichment_timeout,
                        )
                    else:
                        enrichment_code = (
                            gate_resolution_code or isolated_resolution_code
                        )
                else:
                    enrichment_code = (
                        0
                        if (
                            isolated_resolution_code in {None, 0}
                            and gate_resolution_code in {None, 0}
                        )
                        else gate_resolution_code or isolated_resolution_code
                    )
                if enrichment_code == 0 and not _STOP_EVENT.is_set():
                    finalize_source = (
                        collect_dir / "ads.enriched.json"
                        if args.relevant_enrichment
                        else enrichment_source
                    )
                    relevance_code = _run_command(
                        _relevance_classifier_command(
                            collect_dir,
                            stage="finalize",
                            source=finalize_source,
                            include_video=not args.no_video_recording,
                        ),
                        collect_dir / "relevance.log",
                        timeout_seconds=args.relevance_timeout,
                    )
                else:
                    relevance_code = enrichment_code
            else:
                relevance_code = prefilter_code
        else:
            relevance_code = _run_command(
                _relevance_classifier_command(collect_dir),
                collect_dir / "relevance.log",
                timeout_seconds=args.relevance_timeout,
            )
        if relevance_code:
            print(
                f"[{profile.display_name}] relevance classifier code={relevance_code}",
                flush=True,
            )
    elif (
        collect_code == 0
        and args.interest_safe_collection
        and not args.dry_run
        and not relevance_enabled
    ):
        _write_json(collect_dir / "relevance_summary.json", {
            "status": "disabled_in_interest_safe_collection",
            "total": 0,
        })
        print(
            f"[{profile.display_name}] safe collection has no relevance classifier; "
            "active enrichment and backend import are disabled",
            flush=True,
        )
    if (
        collect_code == 0
        and args.import_backend
        and not args.dry_run
        and not _STOP_EVENT.is_set()
        and relevance_code in {None, 0}
        and (not args.interest_safe_collection or relevance_code == 0)
    ):
        import_source = (
            collect_dir / "ads.relevant.json"
            if relevance_code == 0
            else collect_dir / "ads.json"
        )
        if import_source.exists():
            import_code = _run_command(
                _backend_import_command(profile, import_source),
                collect_dir / "backend_import.log",
                timeout_seconds=args.backend_import_timeout,
            )
            if import_code:
                print(
                    f"[{profile.display_name}] backend import code={import_code}",
                    flush=True,
                )
    observed_metrics = collect_run_metrics(
        collect_dir,
        return_code=collect_code,
        default_elapsed_seconds=args.collect_minutes * 60,
    )
    if not profile.expected_country and observed_metrics.profile_country:
        profile.expected_country = observed_metrics.profile_country
        _persist_profile_country(
            Path(args.profiles_json),
            profile.octo_profile_uuid,
            observed_metrics.profile_country,
        )
        print(
            f"[{profile.display_name}] adopted geo={observed_metrics.profile_country}",
            flush=True,
        )
    _update_calibration_pools(profile, collect_dir, root_dir)
    target_count = _count_calibration_targets(profile, collect_dir, root_dir)
    metrics = collect_run_metrics(
        collect_dir,
        expected_country=profile.expected_country,
        return_code=collect_code,
        default_elapsed_seconds=args.collect_minutes * 60,
        calibration_targets_available=target_count,
    )
    history, baseline, calibration_timestamps = store.profile_history(
        profile.octo_profile_uuid,
    )
    recovery_burst_count = store.profile_recovery_burst_count(profile.octo_profile_uuid)
    recovery_evaluation_active = store.profile_recovery_evaluation_active(
        profile.octo_profile_uuid
    )
    evaluation_policy = _profile_evaluation_policy(
        policy,
        recovery_active=recovery_evaluation_active,
        quality_guard=profile.quality_guard,
    )
    calibration_attempt_timestamps = store.profile_calibration_attempts(
        profile.octo_profile_uuid,
    )
    calibration_target_offset = store.profile_calibration_target_offset(
        profile.octo_profile_uuid,
    )
    if baseline.sample_count <= 0:
        baseline = baseline_from_history(history, policy=policy)
    decision = evaluate_calibration_need(
        metrics,
        history=history,
        baseline=baseline,
        policy=evaluation_policy,
        last_calibration_at=calibration_timestamps[-1]
        if calibration_timestamps
        else None,
        calibration_timestamps=calibration_timestamps,
        calibration_attempt_timestamps=calibration_attempt_timestamps,
    )
    _write_json(collect_dir / "health.json", decision.to_dict())
    print(
        f"[{profile.display_name}] health={decision.status} "
        f"ads={metrics.ads_total} target={metrics.target_ads} "
        f"recovery={recovery_burst_count}/{args.recovery_burst_cycles} "
        f"reasons={','.join(decision.reasons) or '-'} "
        f"blockers={','.join(decision.blockers) or '-'}",
        flush=True,
    )

    pipeline_failed = (
        interest_safety_code not in {None, 0}
        or prefilter_code not in {None, 0}
        or isolated_resolution_code not in {None, 0}
        or gate_resolution_code not in {None, 0}
        or enrichment_code not in {None, 0}
        or relevance_code not in {None, 0}
    )
    calibration_records: list[dict[str, Any]] = []
    if decision.should_calibrate and not _STOP_EVENT.is_set() and not pipeline_failed:
        calibration_passes = _calibration_passes_for_cycle(
            profile,
            metrics,
            history,
            recovery_active=recovery_evaluation_active,
        )
        calibration_passes = min(
            calibration_passes,
            _remaining_daily_calibration_attempts(
                calibration_attempt_timestamps,
                limit=policy.max_calibrations_per_24h,
            ),
        )
        remaining_targets = target_count
        for pass_index in range(calibration_passes):
            if (
                _STOP_EVENT.is_set()
                or remaining_targets < policy.min_calibration_targets
            ):
                break
            target_limit_cap = _calibration_pass_target_cap(
                remaining_targets,
                passes_left=calibration_passes - pass_index,
                min_targets=policy.min_calibration_targets,
            )
            calibration_record = _run_calibration(
                profile,
                args,
                collect_dir,
                root_dir,
                decision=decision,
                target_offset=calibration_target_offset,
                target_limit_cap=target_limit_cap,
            )
            calibration_record["pass_index"] = pass_index + 1
            calibration_record["planned_passes"] = calibration_passes
            calibration_records.append(calibration_record)
            consumed = _calibration_targets_consumed(calibration_record)
            calibration_target_offset += consumed
            remaining_targets = max(0, remaining_targets - consumed)
            if pass_index + 1 >= calibration_passes:
                break
            if not _calibration_allows_followup(calibration_record):
                break
            print(
                f"[{profile.display_name}] recovery did not improve; "
                f"calibration pass {pass_index + 2}/{calibration_passes} "
                f"with {remaining_targets} unused targets",
                flush=True,
            )
    elif decision.should_calibrate and pipeline_failed:
        print(
            f"[{profile.display_name}] calibration skipped: collection pipeline failed",
            flush=True,
        )
    return store.record_profile_run(
        profile,
        metrics,
        decision,
        calibrations=calibration_records,
        policy=policy,
        schedule_policy=_profile_schedule_policy(args),
        infrastructure_retry_required=pipeline_failed,
    )


def _interest_safe_collection_violations(run_dir: Path) -> list[str]:
    violations: list[str] = []
    summary = _load_json(run_dir / "summary.json", default={})
    if not isinstance(summary, dict):
        return ["missing_summary"]
    if summary.get("interest_safe_mode") is not True:
        violations.append("safe_mode_not_confirmed")
    if summary.get("resolve_enabled") is not False:
        violations.append("landing_resolution_enabled")

    active_actions = summary.get("active_actions")
    expected_actions = (
        "cta_click_attempts",
        "video_play_attempts",
        "comment_open_attempts",
    )
    if not isinstance(active_actions, dict):
        violations.append("missing_active_action_audit")
    else:
        for action in expected_actions:
            if action not in active_actions:
                violations.append(f"missing_{action}")
            elif _nonnegative_int(active_actions.get(action)) != 0:
                violations.append(f"nonzero_{action}")

    media_guard = summary.get("passive_media_guard")
    if not isinstance(media_guard, dict):
        violations.append("missing_passive_media_guard")
    else:
        for field in (
            "installed",
            "init_script_installed",
            "media_route_installed",
        ):
            if media_guard.get(field) is not True:
                violations.append(f"media_guard_{field}_false")

    ads = _load_json(run_dir / "ads.json", default=None)
    if not isinstance(ads, list):
        violations.append("missing_ads_file")
        return violations
    forbidden_artifacts = (
        "landing_full",
        "landing_clean",
        "landing_screenshot",
        "landing_archive",
        "video",
    )
    for artifact in forbidden_artifacts:
        if any(
            isinstance(raw, dict) and bool(raw.get(artifact))
            for raw in ads
        ):
            violations.append(f"passive_ad_contains_{artifact}")
    return violations


def _collector_command(profile: ProfileConfig, args, run_dir: Path) -> list[str]:
    config = get_config()
    octo_host = args.octo_host or config.facebook.octo_host
    octo_port = args.octo_port or config.facebook.octo_port
    command = [
        config.facebook.runner_python,
        "-m",
        config.facebook.runner_module,
        "--minutes",
        str(args.collect_minutes),
        "--collect-scrolls",
        str(args.collect_scrolls),
        "--resolve-max",
        str(args.resolve_max),
        "--scroll-px",
        str(args.scroll_px),
        "--max-ads-per-view",
        str(args.max_ads_per_view),
        "--landing-archive-timeout",
        str(args.landing_archive_timeout),
        "--landing-archive-max-resources",
        str(args.landing_archive_max_resources),
        "--video-max-seconds",
        str(args.video_max_seconds),
        "--octo-host",
        octo_host,
        "--octo-port",
        str(octo_port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--run-dir",
        str(run_dir),
    ]
    if args.debug:
        command.append("--debug")
    if args.interest_safe_collection:
        command.append("--passive-collect")
    if args.no_video_recording:
        command.append("--no-video-recording")
    if args.no_landing_archives:
        command.append("--no-landing-archives")
    if _octo_headless(args):
        command.append("--octo-headless")
    return command


def _relevance_classifier_command(
    run_dir: Path,
    *,
    stage: str = "standard",
    source: Path | None = None,
    include_video: bool = False,
) -> list[str]:
    config = get_config()
    command = [
        config.facebook.runner_python,
        "-m",
        "app.services.facebook_relevance_classifier",
        "--run-dir",
        str(run_dir),
    ]
    if stage != "standard":
        command.extend(["--stage", stage])
    if source is not None:
        command.extend(["--source", str(source)])
    if include_video:
        command.append("--include-video")
    return command


def _relevant_enricher_command(
    profile: ProfileConfig,
    args,
    run_dir: Path,
    *,
    source: Path | None = None,
) -> list[str]:
    config = get_config()
    octo_host = args.octo_host or config.facebook.octo_host
    octo_port = args.octo_port or config.facebook.octo_port
    command = [
        config.facebook.runner_python,
        "-m",
        "app.services.facebook_ad_enricher",
        "--run-dir",
        str(run_dir),
        "--octo-host",
        octo_host,
        "--octo-port",
        str(octo_port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--timeout-ms",
        str(max(1, round(args.calibration_page_timeout * 1000))),
        "--locate-timeout-ms",
        str(max(0, round(args.calibration_locate_timeout * 1000))),
        "--video-max-seconds",
        str(args.video_max_seconds),
        "--landing-archive-timeout",
        str(args.landing_archive_timeout),
        "--landing-archive-max-resources",
        str(args.landing_archive_max_resources),
    ]
    if source is not None:
        command.extend(["--source", str(source)])
    if args.no_video_recording:
        command.append("--no-record-videos")
    if args.no_landing_archives:
        command.append("--no-resolve-landings")
    if _octo_headless(args):
        command.append("--octo-headless")
    return command


def _isolated_landing_resolver_command(
    profile: ProfileConfig,
    args,
    run_dir: Path,
) -> list[str]:
    config = get_config()
    octo_host = args.octo_host or config.facebook.octo_host
    octo_port = args.octo_port or config.facebook.octo_port
    command = [
        config.facebook.runner_python,
        "-m",
        "app.services.facebook_isolated_landing_resolver",
        "--run-dir",
        str(run_dir),
        "--octo-host",
        octo_host,
        "--octo-port",
        str(octo_port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--timeout-ms",
        str(max(1, round(args.calibration_landing_timeout * 1000))),
        "--landing-ready-seconds",
        str(args.landing_archive_timeout),
        "--landing-archive-max-resources",
        str(args.landing_archive_max_resources),
    ]
    if _octo_headless(args):
        command.append("--octo-headless")
    return command


def _relevance_classification_enabled(args) -> bool:
    if args.classify_relevance is not None:
        return bool(args.classify_relevance)
    return bool(get_config().facebook.relevance_filter_enabled)


def _backend_import_command(
    profile: ProfileConfig,
    ads_json_path: Path,
) -> list[str]:
    config = get_config()
    return [
        config.facebook.runner_python,
        "-m",
        "app.services.facebook_db_importer",
        "--ads-json",
        str(ads_json_path),
        "--title",
        f"{profile.display_name} - {ads_json_path.parent.name}",
    ]


def _calibrator_command(
    profile: ProfileConfig,
    args,
    run_dir: Path,
    ads_paths: list[Path],
    country: str | None,
    *,
    target_offset: int = 0,
    target_limit: int | None = None,
    min_successful_targets: int | None = None,
    max_reactions: int | None = None,
    max_follows: int | None = None,
    max_comments: int | None = None,
    min_interactions: int | None = None,
) -> list[str]:
    config = get_config()
    octo_host = args.octo_host or config.facebook.octo_host
    octo_port = args.octo_port or config.facebook.octo_port
    command = [
        config.facebook.runner_python,
        "-m",
        "app.services.facebook_calibrator",
        "--octo-host",
        octo_host,
        "--octo-port",
        str(octo_port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--limit",
        str(target_limit if target_limit is not None else args.calibration_limit),
        "--target-offset",
        str(max(0, target_offset)),
        "--view-seconds",
        str(args.calibration_view_seconds),
        "--pause-between-targets",
        str(args.calibration_pause),
        "--locate-timeout-ms",
        str(round(max(0.0, args.calibration_locate_timeout) * 1000)),
        "--timeout-ms",
        str(round(max(0.0, args.calibration_page_timeout) * 1000)),
        "--landing-view-seconds",
        str(max(0.0, args.calibration_landing_view_seconds)),
        "--landing-timeout-ms",
        str(round(max(0.0, args.calibration_landing_timeout) * 1000)),
        "--session-minutes",
        str(max(0.0, args.calibration_session_minutes)),
        "--prelander-max-scrolls",
        str(max(0, args.calibration_prelander_max_scrolls)),
        "--quiz-max-questions",
        str(max(0, args.calibration_quiz_max_questions)),
        "--offer-submit-mode",
        str(args.calibration_offer_submit_mode),
        "--offer-success-wait-seconds",
        str(max(0.0, args.calibration_offer_success_wait_seconds)),
        "--max-retained-offer-tabs",
        str(max(1, args.calibration_max_retained_offer_tabs)),
        "--reaction-rate",
        str(args.calibration_reaction_rate),
        "--follow-rate",
        str(args.calibration_follow_rate),
        "--comment-every",
        str(args.calibration_comment_every),
        "--max-reactions",
        str(
            max_reactions
            if max_reactions is not None
            else args.calibration_max_reactions
        ),
        "--max-follows",
        str(max_follows if max_follows is not None else args.calibration_max_follows),
        "--max-comments",
        str(
            max_comments if max_comments is not None else args.calibration_max_comments
        ),
        "--min-interactions",
        str(
            min_interactions
            if min_interactions is not None
            else args.calibration_min_interactions
        ),
        "--min-successful-targets",
        str(
            min_successful_targets
            if min_successful_targets is not None
            else CalibrationPolicy().min_successful_calibration_targets
        ),
        "--run-dir",
        str(run_dir),
        "--target-health-json",
        str(run_dir.parent / "calibration_target_health.json"),
    ]
    command.append(
        "--visit-landing" if args.calibration_visit_landing else "--no-visit-landing"
    )
    command.append(
        "--offer-funnel" if args.calibration_offer_funnel else "--no-offer-funnel"
    )
    command.append(
        "--direct-offer-fallback"
        if args.calibration_direct_offer_fallback
        else "--no-direct-offer-fallback"
    )
    command.append(
        "--repeat-targets-until-deadline"
        if args.calibration_repeat_targets_until_deadline
        else "--no-repeat-targets-until-deadline"
    )
    if args.calibration_offer_identity_json:
        command.extend(
            ["--offer-identity-json", args.calibration_offer_identity_json]
        )
    for domain in args.calibration_offer_submit_allow_domain:
        command.extend(["--offer-submit-allow-domain", domain])
    for template in args.calibration_comment_template:
        command.extend(["--comment-template", template])
    if profile.no_country_filter:
        command.append("--no-country-filter")
    elif country:
        command.extend(["--country", country])
    for ads_path in ads_paths:
        command.extend(["--ads-json", str(ads_path)])
    if _octo_headless(args):
        command.append("--octo-headless")
    return command


def _octo_headless(args) -> bool:
    if args.octo_headless is not None:
        return bool(args.octo_headless)
    return bool(get_config().facebook.octo_headless)


def _calibration_plan(
    decision: CalibrationDecision,
    args,
    available_targets: int,
) -> CalibrationPlan:
    reasons = set(decision.reasons)
    if reasons.intersection(_RECOVERY_CALIBRATION_REASONS):
        tier = "recovery"
        desired_goal = args.calibration_recovery_target_goal
        desired_limit = args.calibration_recovery_target_limit
    elif reasons.intersection(_LOW_RELEVANCE_CALIBRATION_REASONS):
        tier = "low_relevance"
        desired_goal = args.calibration_low_relevance_target_goal
        desired_limit = desired_goal
    else:
        tier = "standard"
        desired_goal = args.calibration_target_goal
        desired_limit = max(args.calibration_limit, desired_goal)

    if args.calibration_offer_funnel:
        desired_goal = min(desired_goal, args.calibration_funnel_target_goal)

    target_limit = min(max(0, available_targets), desired_limit)
    target_goal = min(target_limit, desired_goal)
    if tier == "standard":
        return CalibrationPlan(
            tier=tier,
            target_limit=target_limit,
            target_goal=target_goal,
            max_reactions=args.calibration_max_reactions,
            max_follows=args.calibration_max_follows,
            max_comments=args.calibration_max_comments,
            min_interactions=args.calibration_min_interactions,
        )

    max_reactions = max(
        args.calibration_max_reactions,
        math.ceil(target_limit * 0.30),
    )
    max_follows = max(
        args.calibration_max_follows,
        math.ceil(target_limit * 0.10),
    )
    max_comments = args.calibration_max_comments
    if args.calibration_comment_every > 0:
        possible_comments = math.ceil(
            target_limit / args.calibration_comment_every,
        )
        max_comments = max(max_comments, min(10, possible_comments))
    return CalibrationPlan(
        tier=tier,
        target_limit=target_limit,
        target_goal=target_goal,
        max_reactions=max_reactions,
        max_follows=max_follows,
        max_comments=max_comments,
        min_interactions=max(
            args.calibration_min_interactions,
            math.ceil(target_limit * 0.10),
        ),
    )


def _effective_calibration_target_goal(plan: CalibrationPlan) -> int:
    if plan.tier == "standard" or plan.target_limit <= 10:
        return plan.target_goal
    return min(
        plan.target_goal,
        max(10, math.ceil(plan.target_limit * 0.60)),
    )


def _calibration_passes_for_cycle(
    profile: ProfileConfig,
    metrics: RunMetrics,
    history: list[RunMetrics],
    *,
    recovery_active: bool,
) -> int:
    configured = max(1, profile.failed_recovery_calibration_passes)
    if configured == 1 or not recovery_active:
        return 1
    previous = next(
        (
            item
            for item in reversed(history)
            if item.target_source == "relevance"
            and item.relevance_known
            and item.relevance_classified_ads > 0
            and (
                not metrics.profile_uuid
                or not item.profile_uuid
                or metrics.profile_uuid == item.profile_uuid
            )
        ),
        None,
    )
    if previous is None:
        return 1
    return (
        1 if _relevance_result_meaningfully_improved(metrics, previous) else configured
    )


def _relevance_result_meaningfully_improved(
    current: RunMetrics,
    previous: RunMetrics,
) -> bool:
    current_relevant = int(current.relevant_ads or 0)
    previous_relevant = int(previous.relevant_ads or 0)
    count_gain = current_relevant - previous_relevant
    required_count_gain = max(2, math.ceil(previous_relevant * 0.20))
    if count_gain >= required_count_gain:
        return True
    if (
        current.relevant_rate is not None
        and previous.relevant_rate is not None
        and current.relevant_rate >= previous.relevant_rate + 0.05
    ):
        return True
    return bool(
        current.target_per_hour is not None
        and previous.target_per_hour is not None
        and previous.target_per_hour > 0
        and current.target_per_hour >= previous.target_per_hour * 1.20
    )


def _remaining_daily_calibration_attempts(
    timestamps: list[str],
    *,
    limit: int,
    now: datetime | None = None,
) -> int:
    now_dt = now or datetime.now(UTC)
    since = now_dt - timedelta(hours=24)
    recent = 0
    for value in timestamps:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed >= since:
            recent += 1
    return max(0, max(1, limit) - recent)


def _calibration_pass_target_cap(
    remaining_targets: int,
    *,
    passes_left: int,
    min_targets: int,
) -> int:
    remaining = max(0, remaining_targets)
    passes = max(1, passes_left)
    minimum = max(1, min_targets)
    if passes == 1 or remaining < passes * minimum:
        return remaining
    return max(minimum, math.ceil(remaining / passes))


def _calibration_targets_consumed(calibration: dict[str, Any]) -> int:
    summary = (
        calibration.get("summary")
        if isinstance(calibration.get("summary"), dict)
        else {}
    )
    value = summary.get("visited") or calibration.get("target_limit") or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _calibration_allows_followup(calibration: dict[str, Any]) -> bool:
    summary = (
        calibration.get("summary")
        if isinstance(calibration.get("summary"), dict)
        else {}
    )
    return bool(
        summary.get("status") in {"completed", "dry_run"}
        and not summary.get("infrastructure_error")
        and _calibration_targets_consumed(calibration) > 0
    )


def _run_calibration(
    profile: ProfileConfig,
    args,
    collect_dir: Path,
    root_dir: Path,
    *,
    decision: CalibrationDecision,
    target_offset: int = 0,
    target_limit_cap: int | None = None,
) -> dict[str, Any]:
    cycle_at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    calibration_dir = (
        root_dir / "profiles" / profile.storage_name / f"calibration_{cycle_at}"
    )
    calibration_dir.mkdir(parents=True, exist_ok=True)
    ads_paths = _calibration_ads_paths(profile, collect_dir, root_dir)
    available_targets = _count_calibration_targets(
        profile,
        collect_dir,
        root_dir,
    )
    available_for_pass = available_targets
    if target_limit_cap is not None:
        available_for_pass = min(available_for_pass, max(0, target_limit_cap))
    plan = _calibration_plan(decision, args, available_for_pass)
    metrics = collect_run_metrics(
        collect_dir,
        expected_country=profile.expected_country,
        default_elapsed_seconds=args.collect_minutes * 60,
    )
    country = metrics.profile_country or profile.expected_country
    print(
        f"[{profile.display_name}] calibration -> {calibration_dir} "
        f"targets_from={len(ads_paths)} available={available_targets} "
        f"pass_available={available_for_pass} tier={plan.tier} "
        f"limit={plan.target_limit} goal={plan.target_goal}",
        flush=True,
    )
    code = 0
    if not args.dry_run:
        code = _run_command(
            _calibrator_command(
                profile,
                args,
                calibration_dir,
                ads_paths,
                country,
                target_offset=target_offset,
                target_limit=plan.target_limit,
                min_successful_targets=plan.target_goal,
                max_reactions=plan.max_reactions,
                max_follows=plan.max_follows,
                max_comments=plan.max_comments,
                min_interactions=plan.min_interactions,
            ),
            calibration_dir / "calibrator.log",
            timeout_seconds=_calibration_timeout_seconds(
                args,
                target_limit=plan.target_limit,
            ),
        )
    summary = _load_json(calibration_dir / "summary.json", default={})
    successful_targets = int(summary.get("ok") or 0)
    effective_target_goal = _effective_calibration_target_goal(plan)
    effective = (
        summary.get("status") == "completed"
        and successful_targets >= effective_target_goal
        and summary.get("interaction_goal_met") is True
    )
    return {
        "at": utc_now(),
        "run_dir": str(calibration_dir),
        "return_code": code,
        "summary": summary,
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at") or utc_now(),
        "ads_json": [str(path) for path in ads_paths],
        "effective": effective,
        "successful_targets": successful_targets,
        "tier": plan.tier,
        "target_limit": plan.target_limit,
        "targets_available": available_targets,
        "pass_targets_available": available_for_pass,
        "target_goal": plan.target_goal,
        "effective_target_goal": effective_target_goal,
        "interaction_limits": {
            "max_reactions": plan.max_reactions,
            "max_follows": plan.max_follows,
            "max_comments": plan.max_comments,
            "min_interactions": plan.min_interactions,
        },
    }


def _run_command(
    command: list[str],
    log_path: Path,
    *,
    timeout_seconds: float | None = None,
    interrupt_grace_seconds: float = 30.0,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(get_config().paths.src_path))
    env["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"
    with log_path.open("ab", buffering=0) as log_file:
        process = subprocess.Popen(
            command,
            cwd=get_config().paths.src_path.parent,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        with _ACTIVE_PROCESS_LOCK:
            _ACTIVE_PROCESSES.add(process)
        try:
            return process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _write_log_line(
                log_file,
                f"[orchestrator] command timeout after {timeout_seconds:.1f}s; sending SIGINT",
            )
            _signal_process_group(process, signal.SIGINT)
            try:
                process.wait(timeout=interrupt_grace_seconds)
            except subprocess.TimeoutExpired:
                _write_log_line(
                    log_file,
                    "[orchestrator] SIGINT grace expired; sending SIGTERM",
                )
                _signal_process_group(process, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _write_log_line(
                        log_file,
                        "[orchestrator] SIGTERM grace expired; sending SIGKILL",
                    )
                    _signal_process_group(process, signal.SIGKILL)
                    process.wait()
            return 124
        except KeyboardInterrupt:
            _write_log_line(log_file, "[orchestrator] interrupted; forwarding SIGINT")
            _signal_process_group(process, signal.SIGINT)
            try:
                process.wait(timeout=interrupt_grace_seconds)
            except subprocess.TimeoutExpired:
                _signal_process_group(process, signal.SIGTERM)
            raise
        finally:
            with _ACTIVE_PROCESS_LOCK:
                _ACTIVE_PROCESSES.discard(process)


def _calibration_timeout_seconds(
    args,
    *,
    target_limit: int | None = None,
) -> float:
    if args.calibration_offer_funnel and args.calibration_session_minutes > 0:
        return max(
            300.0,
            args.calibration_session_minutes * 60
            + args.calibration_page_timeout
            + args.calibration_landing_timeout
            + args.calibration_timeout_grace,
        )
    per_target = (
        args.calibration_view_seconds
        + args.calibration_pause
        + args.calibration_locate_timeout
        + args.calibration_page_timeout
        + (
            args.calibration_landing_view_seconds
            + args.calibration_landing_timeout
            if args.calibration_visit_landing
            else 0.0
        )
        + 3.0
    )
    return max(
        300.0,
        (target_limit if target_limit is not None else args.calibration_limit)
        * per_target
        + args.calibration_timeout_grace,
    )


def _write_log_line(log_file, message: str) -> None:
    log_file.write(f"\n{message}\n".encode())


def _signal_process_group(process: subprocess.Popen, sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.send_signal(sig)
        except OSError:
            pass


def _request_orchestrator_stop(_signum, _frame) -> None:
    _STOP_EVENT.set()
    with _ACTIVE_PROCESS_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        _signal_process_group(process, signal.SIGINT)


def _evaluate(args) -> int:
    policy = CalibrationPolicy()
    store = StateStore(Path(args.state_json))
    history, baseline, calibration_timestamps = store.profile_history(args.profile_uuid)
    calibration_attempt_timestamps = store.profile_calibration_attempts(
        args.profile_uuid
    )
    metrics = collect_run_metrics(
        args.run_dir,
        expected_country=args.expected_country or None,
        return_code=args.return_code,
        default_elapsed_seconds=args.default_elapsed_seconds,
        default_scrolls=args.default_scrolls,
        calibration_targets_available=args.calibration_targets,
    )
    current_path = Path(metrics.run_dir).expanduser().resolve()
    history = [
        item
        for item in history
        if Path(item.run_dir).expanduser().resolve() != current_path
    ]
    baseline_contains_current = any(
        Path(run_dir).expanduser().resolve() == current_path
        for run_dir in baseline.source_run_dirs
    )
    if baseline.sample_count <= 0 or baseline_contains_current:
        baseline = baseline_from_history(history, policy=policy)
    decision = evaluate_calibration_need(
        metrics,
        history=history,
        baseline=baseline,
        policy=policy,
        last_calibration_at=calibration_timestamps[-1]
        if calibration_timestamps
        else None,
        calibration_timestamps=calibration_timestamps,
        calibration_attempt_timestamps=calibration_attempt_timestamps,
    )
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not decision.should_calibrate else 10


def _seed_baseline(args) -> int:
    policy = CalibrationPolicy()
    metrics = collect_run_metrics(
        args.run_dir,
        expected_country=args.expected_country or None,
        default_elapsed_seconds=args.default_elapsed_seconds,
        default_scrolls=args.default_scrolls,
    )
    if not is_good_baseline_candidate(metrics, policy):
        print(
            "Run is not a good baseline candidate. "
            "Use a complete, geo-matched run with enough ads and targets.",
            flush=True,
        )
        print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))
        return 1
    baseline = StateStore(Path(args.state_json)).seed_baseline(
        args.profile_uuid,
        metrics,
        label=args.label,
        expected_country=args.expected_country or None,
        policy=policy,
    )
    print(json.dumps(baseline.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _discover_active(args) -> int:
    profiles_path = Path(args.profiles_json)
    profiles = _load_profiles(profiles_path)
    existing = {profile.octo_profile_uuid for profile in profiles}
    active = _octo_local_get(args.octo_host, args.octo_port, "/api/profiles/active")
    added = 0
    for raw in active if isinstance(active, list) else []:
        uuid = str(raw.get("uuid") or "")
        if not uuid or uuid in existing:
            continue
        country = (raw.get("connection_data") or {}).get("country")
        profiles.append(
            ProfileConfig(
                octo_profile_uuid=uuid,
                label=str(raw.get("title") or raw.get("name") or uuid[:8]),
                expected_country=str(country) if country else None,
                enabled=bool(args.enable_new),
            )
        )
        added += 1
    _write_json(profiles_path, {"profiles": [asdict(profile) for profile in profiles]})
    print(f"active={len(active) if isinstance(active, list) else 0} added={added}")
    return 0


def _discover_public(args) -> int:
    added = _merge_public_profiles(
        Path(args.profiles_json),
        token=args.octo_api_token or os.environ.get("OCTO_API_TOKEN", ""),
        search_tags=args.octo_search_tags,
        enable_new=bool(args.enable_new),
    )
    print(f"added={added}")
    return 0


def _merge_public_profiles(
    profiles_path: Path,
    *,
    token: str,
    search_tags: str = "",
    enable_new: bool = False,
) -> int:
    if not token:
        raise RuntimeError("Octo Public API token is required")
    public_profiles = _octo_public_profiles(token, search_tags=search_tags)
    with _PROFILES_FILE_LOCK:
        profiles = _load_profiles(profiles_path)
        existing = {profile.octo_profile_uuid for profile in profiles}
        added = 0
        for raw in public_profiles:
            uuid = str(raw.get("uuid") or "")
            if not uuid or uuid in existing:
                continue
            profiles.append(
                ProfileConfig(
                    octo_profile_uuid=uuid,
                    label=str(raw.get("title") or uuid[:8]),
                    # The Local API start response is the authority for geo. Public
                    # API proxy hints may be ISO codes or stale proxy metadata.
                    expected_country=None,
                    enabled=enable_new,
                )
            )
            existing.add(uuid)
            added += 1
        if added:
            _write_json(
                profiles_path, {"profiles": [asdict(profile) for profile in profiles]}
            )
    return added


def _load_profiles(path: Path) -> list[ProfileConfig]:
    payload = _load_json(path, default={"profiles": []})
    raw_profiles = payload.get("profiles", []) if isinstance(payload, dict) else payload
    return [
        ProfileConfig.from_dict(raw)
        for raw in raw_profiles
        if isinstance(raw, dict) and raw.get("octo_profile_uuid")
    ]


def _persist_profile_country(path: Path, profile_uuid: str, country: str) -> None:
    with _PROFILES_FILE_LOCK:
        payload = _load_json(path, default={"profiles": []})
        raw_profiles = (
            payload.get("profiles", []) if isinstance(payload, dict) else payload
        )
        changed = False
        for raw in raw_profiles if isinstance(raw_profiles, list) else []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("octo_profile_uuid") or "") != profile_uuid:
                continue
            if not raw.get("expected_country"):
                raw["expected_country"] = country
                changed = True
            break
        if changed:
            _write_json(path, {"profiles": raw_profiles})


def _calibration_was_effective(raw: dict[str, Any]) -> bool:
    if "effective" in raw:
        return bool(raw.get("effective"))
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    return (
        raw.get("return_code") == 0
        and summary.get("status") == "completed"
        and int(summary.get("ok") or 0)
        >= CalibrationPolicy().min_successful_calibration_targets
        and summary.get("interaction_goal_met") is True
    )


def _count_calibration_targets(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> int:
    ads_paths = _calibration_ads_paths(profile, collect_dir, root_dir)
    if not ads_paths:
        return 0
    country = None if profile.no_country_filter else profile.expected_country
    try:
        return len(
            load_saved_facebook_targets_from_ads_json(
                ads_paths,
                country=country,
                limit=10_000,
                include_direct_offers=True,
                excluded_urls=quarantined_facebook_post_urls(
                    collect_dir.parent / "calibration_target_health.json"
                ),
            )
        )
    except Exception:
        return 0


def _calibration_ads_paths(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> list[Path]:
    paths: list[Path] = []
    fresh = collect_dir / "ads.relevant.json"
    if fresh.exists() and _has_direct_relevant_ads(fresh):
        paths.append(fresh)
    active_root = root_dir or (
        collect_dir.parents[2] if len(collect_dir.parents) >= 3 else None
    )
    pool_candidates = [collect_dir.parent / "calibration_pool.json"]
    if active_root and profile.expected_country:
        pool_candidates.append(
            active_root
            / "calibration_pools"
            / f"{_safe_name(profile.expected_country)}.json"
        )
    for candidate in pool_candidates:
        if (
            candidate.exists()
            and candidate not in paths
            and _has_direct_relevant_ads(candidate)
        ):
            paths.append(candidate)
    for value in profile.calibration_ads_json:
        path = Path(value).expanduser()
        relevant_variant = path.with_name("ads.relevant.json")
        candidate = relevant_variant if relevant_variant.exists() else path
        if (
            candidate.exists()
            and candidate not in paths
            and _has_direct_relevant_ads(candidate)
        ):
            paths.append(candidate)
    return paths


def _update_calibration_pools(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path,
) -> None:
    fresh = collect_dir / "ads.relevant.json"
    fresh_ads = _load_json(fresh, default=[])
    if not isinstance(fresh_ads, list):
        fresh_ads = []
    pool_paths = [collect_dir.parent / "calibration_pool.json"]
    if profile.expected_country:
        pool_paths.append(
            root_dir
            / "calibration_pools"
            / f"{_safe_name(profile.expected_country)}.json"
        )
    with _POOL_FILE_LOCK:
        for pool_path in pool_paths:
            previous = _load_json(pool_path, default=[])
            previous_ads = previous if isinstance(previous, list) else []
            combined = [
                item
                for item in [*fresh_ads, *previous_ads]
                if isinstance(item, dict) and _ad_is_direct_calibration_target(item)
            ]
            unique: list[dict[str, Any]] = []
            seen: set[str] = set()
            for index, item in enumerate(combined):
                key = str(
                    item.get("facebook_post_url")
                    or item.get("fb_ad_id")
                    or item.get("landing_clean")
                    or item.get("landing_full")
                    or item.get("screenshot")
                    or f"item:{index}"
                )
                if key in seen:
                    continue
                seen.add(key)
                unique.append(item)
                if len(unique) >= 1000:
                    break
            _write_json(pool_path, unique)


def _has_relevant_ads(path: Path) -> bool:
    payload = _load_json(path, default=[])
    if not isinstance(payload, list):
        return False
    for raw in payload:
        if isinstance(raw, dict) and _ad_is_relevant(raw):
            return True
    return False


def _has_direct_relevant_ads(path: Path) -> bool:
    payload = _load_json(path, default=[])
    return isinstance(payload, list) and any(
        isinstance(raw, dict) and _ad_is_direct_calibration_target(raw)
        for raw in payload
    )


def _ad_is_direct_calibration_target(raw: dict[str, Any]) -> bool:
    post_url = str(raw.get("facebook_post_url") or "")
    try:
        parsed = urllib.parse.urlparse(post_url)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    facebook_host = host == "facebook.com" or host.endswith(".facebook.com")
    query = urllib.parse.parse_qs(parsed.query)
    direct_path = "/posts/" in parsed.path
    direct_query = (
        parsed.path.rstrip("/").endswith(("story.php", "permalink.php"))
        and bool((query.get("story_fbid") or [""])[0])
        and bool((query.get("id") or [""])[0])
    )
    direct_post = facebook_host and (direct_path or direct_query)
    direct_offer = str(raw.get("landing_full") or raw.get("landing_clean") or "")
    try:
        offer = urllib.parse.urlparse(direct_offer)
        usable_offer = offer.scheme in {"http", "https"} and bool(offer.hostname)
    except ValueError:
        usable_offer = False
    return _ad_is_relevant(raw) and (direct_post or usable_offer)


def _ad_is_relevant(raw: dict[str, Any]) -> bool:
    relevance = raw.get("relevance")
    return (
        raw.get("relevant") is True
        or (isinstance(relevance, dict) and relevance.get("result") == "relevant")
        or (isinstance(relevance, str) and relevance.casefold() == "relevant")
    )


def _safe_name(value: str) -> str:
    name = "".join(
        char.lower() if char.isascii() and char.isalnum() else "_" for char in value
    )
    return "_".join(part for part in name.split("_") if part) or "unknown"


def _octo_local_get(host: str, port: int, path: str) -> dict | list:
    request = urllib.request.Request(
        f"http://{host}:{port}{path}",
        method="GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Octo Local API failed: HTTP {exc.code}") from exc


def _octo_local_post(
    host: str,
    port: int,
    path: str,
    body: dict[str, Any],
) -> dict | list:
    request = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Octo Local API failed: HTTP {exc.code}") from exc


def _stop_octo_profile(profile: ProfileConfig, args) -> None:
    config = get_config()
    host = args.octo_host or config.facebook.octo_host
    port = args.octo_port or config.facebook.octo_port
    try:
        active = _octo_local_get(host, port, "/api/profiles/active")
        is_active = isinstance(active, list) and any(
            str(item.get("uuid") or "") == profile.octo_profile_uuid
            for item in active
            if isinstance(item, dict)
        )
        if not is_active:
            return
        _octo_local_post(
            host,
            port,
            "/api/profiles/stop",
            {"uuid": profile.octo_profile_uuid},
        )
        print(f"[{profile.display_name}] Octo profile stopped", flush=True)
    except Exception as exc:
        print(
            f"[{profile.display_name}] Octo profile stop failed: {exc!r}",
            flush=True,
        )


def _octo_public_profiles(token: str, *, search_tags: str = "") -> list[dict[str, Any]]:
    page = 0
    page_len = 100
    profiles: list[dict[str, Any]] = []
    while True:
        query = (
            f"page_len={page_len}&page={page}"
            "&fields=title,description,proxy,tags,status,last_active,extra_info"
            "&ordering=active"
        )
        if search_tags:
            query += f"&search_tags={urllib.parse.quote(search_tags)}"
        request = urllib.request.Request(
            f"https://app.octobrowser.net/api/v2/automation/profiles?{query}",
            method="GET",
            headers={
                "Content-Type": "application/json",
                "X-Octo-Api-Token": token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Octo Public API failed: HTTP {exc.code}") from exc
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(data, list) or not data:
            break
        profiles.extend(item for item in data if isinstance(item, dict))
        total_count = int(payload.get("total_count") or len(profiles))
        if len(profiles) >= total_count:
            break
        page += 1
    return profiles


def _public_profile_country_hint(raw: dict[str, Any]) -> str | None:
    extra_info = (
        raw.get("extra_info") if isinstance(raw.get("extra_info"), dict) else {}
    )
    proxy = raw.get("proxy") if isinstance(raw.get("proxy"), dict) else {}
    for key in ("country", "geo", "profile_country"):
        value = extra_info.get(key) or proxy.get(key)
        if value:
            return str(value)
    return None


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
