from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

from app.facebook.collection import CollectedAd
from app.facebook.profiles import normalize_country
from app.services import facebook_runner

from ..adapters.playwright import DebugRecorder, collect_feed
from ..models import utc_now
from ..stop import stop_requested
from .artifacts import (
    fast_exit_after_browser_operation_timeout,
    write_octo_start_failure,
    write_run_meta,
)
from .configuration import feed_url, run_directory
from .session import run_browser_session


def run_command(args: argparse.Namespace) -> int:
    facebook_runner.OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    facebook_runner.OCTO_PROFILE_UUID = args.octo_profile_uuid
    facebook_runner.OCTO_HEADLESS = args.octo_headless

    target_feed_url = feed_url(args)
    run_dir = run_directory(args)
    run_dir.mkdir(parents=True, exist_ok=True)
    debug = DebugRecorder(run_dir, args.debug, clock=utc_now)
    runner_started_at = utc_now()
    runner_started_monotonic = time.monotonic()
    try:
        ws_endpoint, connection = facebook_runner.get_cdp_endpoint()
        ws_endpoint = facebook_runner.rewrite_cdp_endpoint_host(
            ws_endpoint,
            args.octo_host,
        )
        profile_country = normalize_country(connection.get("country"))
        print(
            f"[octo] CDP {ws_endpoint}  ip={connection.get('ip')} "
            f"country={profile_country}"
        )
        write_run_meta(
            run_dir,
            {
                "collector_metric_version": facebook_runner.COLLECTOR_METRIC_VERSION,
                "octo_profile_uuid": args.octo_profile_uuid,
                "octo_host": args.octo_host,
                "octo_port": args.octo_port,
                "octo_headless": args.octo_headless,
                "octo_ip": connection.get("ip"),
                "profile_country": profile_country,
                "connection_data": connection,
                "started_at": runner_started_at,
            },
        )
        debug.event("octo_connected", ws=ws_endpoint, connection=connection)

        ads = run_browser_session(
            args,
            ws_endpoint=ws_endpoint,
            run_dir=run_dir,
            feed_url=target_feed_url,
            profile_country=profile_country,
            debug=debug,
            collect=collect_feed,
            stop_requested=stop_requested,
        )
        fast_exit_after_browser_operation_timeout(run_dir)
        print_result(ads, run_dir=run_dir, debug_enabled=args.debug)
        return 0
    except facebook_runner.OctoApiError as exc:
        reason = write_octo_start_failure(
            run_dir,
            profile_uuid=args.octo_profile_uuid,
            octo_host=args.octo_host,
            octo_port=args.octo_port,
            octo_headless=args.octo_headless,
            requested_minutes=args.minutes,
            started_at=runner_started_at,
            elapsed_seconds=time.monotonic() - runner_started_monotonic,
            error=exc,
            clock=utc_now,
            metric_version=facebook_runner.COLLECTOR_METRIC_VERSION,
        )
        debug.event("main_failed", error=repr(exc))
        print(f"[octo error:{reason}] {exc}", file=sys.stderr, flush=True)
        if args.debug:
            print(f"debug: {run_dir}/debug/", file=sys.stderr, flush=True)
        return 2
    except BaseException as exc:
        debug.event("main_failed", error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        debug.close()


def print_result(
    ads: dict[str, CollectedAd],
    *,
    run_dir: Path,
    debug_enabled: bool,
) -> None:
    by_type: dict[str, int] = {}
    resolved = 0
    for ad in ads.values():
        by_type[ad.ad_type] = by_type.get(ad.ad_type, 0) + 1
        if ad.landing_full:
            resolved += 1
    print("\n=== DONE ===")
    print(f"unique ads: {len(ads)}  by_type: {by_type}")
    print(f"full landing resolved: {resolved}")
    print(f"results: {run_dir}/ads.json")
    if debug_enabled:
        print(f"debug: {run_dir}/debug/")
