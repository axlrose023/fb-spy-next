from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Callable
from typing import Any

from app.services import facebook_runner
from app.settings import get_config

from ..funnel import redact_error
from ..models import CalibrationRunResult
from .artifacts import CalibrationArtifacts
from .configuration import (
    load_saved_targets,
    public_args,
    resolve_run_dir,
    should_connect_before_targets,
)
from .session import run_browser_session


def run_command(
    args: argparse.Namespace,
    *,
    stop_requested: Callable[[], bool],
) -> int:
    config = get_config()
    profile_uuid = args.octo_profile_uuid or config.facebook.octo_profile_uuid
    facebook_runner.OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    facebook_runner.OCTO_PROFILE_UUID = profile_uuid
    facebook_runner.OCTO_HEADLESS = args.octo_headless

    run_dir = resolve_run_dir(args)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = CalibrationArtifacts(
        run_dir,
        target_health_path=args.target_health_json,
        utc_now=facebook_runner.utc_now,
    )
    try:
        ws_endpoint, connection_data, profile_country = _connect(args)
        selected_country = (
            None if args.no_country_filter else (args.country or profile_country)
        )
        meta = _run_meta(
            args,
            run_dir=str(run_dir),
            profile_uuid=profile_uuid,
            connection_data=connection_data,
            profile_country=profile_country,
            selected_country=selected_country,
        )
        artifacts.start(meta)
        targets = load_saved_targets(args, selected_country)
        artifacts.save_targets(targets)
        print(
            f"[calibration] targets={len(targets)} "
            f"country={selected_country or 'all'} profile={profile_uuid} "
            f"run_dir={run_dir}",
            flush=True,
        )
        if not targets:
            artifacts.finish(_empty_summary(facebook_runner.utc_now()))
            return 1
        if args.dry_run:
            artifacts.finish(
                {
                    "status": "dry_run",
                    "finished_at": facebook_runner.utc_now(),
                    "targets": len(targets),
                    "ok": 0,
                    "failed": 0,
                }
            )
            return 0

        result, funnel_summary = run_browser_session(
            args,
            ws_endpoint=ws_endpoint,
            targets=targets,
            profile_uuid=profile_uuid,
            selected_country=selected_country,
            artifacts=artifacts,
            stop_requested=stop_requested,
        )
        summary = _completed_summary(
            result,
            target_count=len(targets),
            funnel_summary=funnel_summary,
            artifacts=artifacts,
        )
        artifacts.finish(summary)
        _print_result(result)
        return 0 if result.successful else 2
    except KeyboardInterrupt:
        artifacts.interrupt(len(artifacts.results))
        return 130
    except Exception as exc:
        summary = {
            "status": "failed",
            "finished_at": facebook_runner.utc_now(),
            "error": redact_error(exc),
            "traceback": redact_error(traceback.format_exc()),
            "visited": len(artifacts.results),
        }
        artifacts.fail(summary)
        print(f"[calibration error] {exc!r}", file=sys.stderr, flush=True)
        return 2


def _connect(args: argparse.Namespace) -> tuple[str, dict[str, Any], str | None]:
    if not should_connect_before_targets(args):
        return "", {}, None
    ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()
    endpoint = facebook_runner.rewrite_cdp_endpoint_host(
        ws_endpoint,
        args.octo_host,
    )
    country = facebook_runner.normalize_country(connection_data.get("country"))
    return endpoint, connection_data, country


def _run_meta(
    args: argparse.Namespace,
    *,
    run_dir: str,
    profile_uuid: str,
    connection_data: dict[str, Any],
    profile_country: str | None,
    selected_country: str | None,
) -> dict[str, Any]:
    return {
        "mode": "calibration",
        "started_at": facebook_runner.utc_now(),
        "run_dir": run_dir,
        "octo_profile_uuid": profile_uuid,
        "octo_host": args.octo_host,
        "octo_port": args.octo_port,
        "octo_ip": connection_data.get("ip"),
        "profile_country": profile_country,
        "selected_country": selected_country,
        "source": "ads_json" if args.ads_json else "db",
        "args": public_args(args),
        "connection_data": connection_data,
    }


def _empty_summary(finished_at: str) -> dict[str, Any]:
    return {
        "status": "no_direct_facebook_targets",
        "finished_at": finished_at,
        "targets": 0,
        "ok": 0,
        "failed": 0,
    }


def _completed_summary(
    result: CalibrationRunResult,
    *,
    target_count: int,
    funnel_summary: dict[str, Any],
    artifacts: CalibrationArtifacts,
) -> dict[str, Any]:
    summary = {
        "status": (
            "interrupted"
            if result.termination == "stop_requested"
            else "infrastructure_error"
            if result.infrastructure_error
            else "completed"
        ),
        "finished_at": facebook_runner.utc_now(),
        "targets": target_count,
        "visited": len(result.results),
        "ok": result.ok,
        "failed": result.failed,
        "target_goal_met": result.target_goal_met,
        "interaction_goal_met": result.interaction_goal_met,
        "interactions": result.interactions,
        "offer_funnel": funnel_summary,
        "results_path": str(artifacts.results_path),
        "targets_path": str(artifacts.targets_path),
        "engagement_results_path": str(artifacts.engagement_results_path),
    }
    if result.infrastructure_error:
        summary["infrastructure_error"] = result.infrastructure_error
    return summary


def _print_result(result: CalibrationRunResult) -> None:
    counts = result.interactions
    print(
        f"[calibration done] visited={len(result.results)} ok={result.ok} "
        f"failed={result.failed} interactions={counts['successful']} "
        f"active={counts['already_active']} satisfied={counts['satisfied']}",
        flush=True,
    )
