from __future__ import annotations

import sys
import traceback
from typing import Any

from playwright.sync_api import sync_playwright

from app.services import facebook_runner
from app.settings import get_config

from ..evidence.policy import resolution_candidate, summarize_isolated_resolutions
from ..files import append_json_event, load_ads, write_json
from .isolation import (
    NetworkGuard,
    configure_isolated_context,
    host_is_public,
    new_isolated_context,
)
from .landing_capture import resolve_landing, reuse_resolution


def run_isolated_browser(args: Any) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    source_path = (
        args.source.expanduser().resolve()
        if args.source
        else run_dir / "ads.prefilter.json"
    )
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else run_dir / "ads.isolated.json"
    )
    summary_path = run_dir / "isolated_resolution_summary.json"
    events_path = run_dir / "isolated_resolution_events.jsonl"
    if not source_path.exists():
        write_json(
            summary_path,
            {"status": "no_prefilter_file", "source": str(source_path)},
        )
        return 2

    rows = load_ads(source_path)
    candidates = _prepare_candidates(rows)
    if not candidates:
        write_json(output_path, rows)
        write_json(summary_path, _summary(rows, status="completed"))
        print("[isolated resolver] no resolvable held cards", flush=True)
        return 0

    _configure_octo(args)
    try:
        profile_uuid = args.octo_profile_uuid or get_config().facebook.octo_profile_uuid
        ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()
        ws_endpoint = facebook_runner.rewrite_cdp_endpoint_host(
            ws_endpoint,
            args.octo_host,
        )
        append_json_event(
            events_path,
            {
                "at": facebook_runner.utc_now(),
                "kind": "started",
                "profile_uuid": profile_uuid,
                "profile_country": facebook_runner.normalize_country(
                    connection_data.get("country")
                ),
                "candidates": len(candidates),
            },
        )
        _resolve_candidates(
            args,
            rows,
            candidates,
            run_dir=run_dir,
            output_path=output_path,
            events_path=events_path,
            ws_endpoint=ws_endpoint,
        )
        write_json(output_path, rows)
        summary = _summary(rows, status="completed")
        write_json(summary_path, summary)
        append_json_event(
            events_path,
            {"at": facebook_runner.utc_now(), "kind": "finished", **summary},
        )
        if (
            summary["authenticated_profile_actions_started"]
            or summary["isolation_violations"]
        ):
            print(
                "[isolated resolver invariant] authenticated profile action detected",
                file=sys.stderr,
                flush=True,
            )
            return 4
        print(
            f"[isolated resolver] held={summary['held']} "
            f"resolved={summary['resolved']} unresolved={summary['unresolved']} "
            f"meta_blocked={summary['meta_requests_blocked']}",
            flush=True,
        )
        return 0
    except Exception as exc:
        write_json(output_path, rows)
        summary = _summary(rows, status="infrastructure_error")
        summary["error"] = repr(exc)
        summary["traceback"] = traceback.format_exc()
        write_json(summary_path, summary)
        print(f"[isolated resolver error] {exc!r}", file=sys.stderr, flush=True)
        return 2


def _prepare_candidates(
    rows: list[dict[str, Any]],
) -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, str, str]] = []
    for index, row in enumerate(rows):
        if row.get("relevance_gate") != "hold":
            continue
        candidate = resolution_candidate(row, host_is_public=host_is_public)
        if candidate.resolvable:
            candidates.append((index, candidate.source, candidate.target))
            continue
        row["isolated_resolution"] = {
            "status": candidate.issue,
            "cookie_isolated": True,
            "separate_browser_context": True,
            "facebook_cookie_count_before": 0,
            "authenticated_profile_context": False,
            "active_profile_actions_started": False,
            "isolated_navigation_started": False,
            "external_navigation_started": False,
        }
    return candidates


def _configure_octo(args: Any) -> None:
    config = get_config()
    profile_uuid = args.octo_profile_uuid or config.facebook.octo_profile_uuid
    facebook_runner.OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    facebook_runner.OCTO_PROFILE_UUID = profile_uuid
    facebook_runner.OCTO_HEADLESS = args.octo_headless


def _resolve_candidates(
    args: Any,
    rows: list[dict[str, Any]],
    candidates: list[tuple[int, str, str]],
    *,
    run_dir: Any,
    output_path: Any,
    events_path: Any,
    ws_endpoint: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(ws_endpoint)
        profile_context = browser.contexts[0] if browser.contexts else None
        resolved_cache: dict[str, dict[str, Any]] = {}
        for sequence, (row_index, source, target) in enumerate(candidates, start=1):
            cache_key = f"{source}:{target}"
            if cache_key in resolved_cache:
                reuse_resolution(
                    rows[row_index],
                    resolved_cache[cache_key],
                    source_row_index=resolved_cache[cache_key]["row_index"],
                )
                continue
            context = new_isolated_context(browser)
            try:
                if context == profile_context:
                    raise RuntimeError(
                        "isolated resolver received the persistent profile context"
                    )
                cookies = context.cookies(
                    ["https://www.facebook.com", "https://m.facebook.com"]
                )
                if cookies:
                    raise RuntimeError(
                        "isolated context unexpectedly contains Facebook cookies"
                    )
                append_json_event(
                    events_path,
                    {
                        "at": facebook_runner.utc_now(),
                        "kind": "isolation_verified",
                        "row_index": row_index,
                        "source": source,
                        "separate_browser_context": True,
                        "facebook_cookie_count_before": len(cookies),
                    },
                )
                guard = NetworkGuard(
                    allow_anonymous_facebook=source == "anonymous_facebook_post"
                )
                configure_isolated_context(context, guard)
                resolved, result = resolve_landing(
                    context,
                    rows[row_index],
                    target,
                    source=source,
                    sequence=sequence,
                    run_dir=run_dir,
                    args=args,
                    network_guard=guard,
                    facebook_cookie_count_before=len(cookies),
                )
                rows[row_index] = resolved
                resolved_cache[cache_key] = {"row_index": row_index, "row": resolved}
                append_json_event(
                    events_path,
                    {
                        "at": facebook_runner.utc_now(),
                        "kind": "candidate_finished",
                        "row_index": row_index,
                        **result,
                    },
                )
                write_json(output_path, rows)
            finally:
                context.close()


def _summary(rows: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    return summarize_isolated_resolutions(
        rows,
        status=status,
        finished_at=facebook_runner.utc_now(),
    )
