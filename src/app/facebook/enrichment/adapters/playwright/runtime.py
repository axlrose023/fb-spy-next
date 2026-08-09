from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.services import facebook_runner
from app.settings import get_config

from ...files import append_event, load_ads, write_json
from ...models import EnrichmentOptions
from ...service import EnrichmentService
from .capture import PlaywrightRelevantAdExecutor


def run(args: Any, *, stop_requested: Callable[[], bool]) -> int:
    paths = _paths(args)
    if not paths["source"].exists():
        write_json(
            paths["summary"],
            {"status": "no_prefilter_file", "source": str(paths["source"])},
        )
        return 2
    rows = load_ads(paths["source"])
    service = EnrichmentService(clock=facebook_runner.utc_now)
    candidate_indexes = service.prepare(rows)
    if not candidate_indexes:
        write_json(paths["output"], rows)
        write_json(paths["summary"], service.summary(rows, status="completed"))
        print("[enrichment] no allowed candidates; no browser actions", flush=True)
        return 0
    _configure_profile(args)
    try:
        status, infrastructure_error = _run_candidates(
            args,
            paths,
            rows,
            candidate_indexes,
            service,
            stop_requested,
        )
        summary = _write_completed(
            paths,
            rows,
            service,
            status=status,
            error=infrastructure_error,
        )
        _print_summary(summary, status)
        if summary["active_actions_on_blocked_ads"]:
            print(
                "[enrichment invariant] active action reached a blocked ad",
                file=sys.stderr,
                flush=True,
            )
            return 4
        if stop_requested():
            return 130
        return 2 if infrastructure_error else 0
    except KeyboardInterrupt:
        write_json(paths["output"], rows)
        write_json(paths["summary"], service.summary(rows, status="interrupted"))
        return 130
    except Exception as exc:
        write_json(paths["output"], rows)
        summary = service.summary(rows, status="infrastructure_error")
        summary.update({"error": repr(exc), "traceback": traceback.format_exc()})
        write_json(paths["summary"], summary)
        print(f"[enrichment error] {exc!r}", file=sys.stderr, flush=True)
        return 2


def _run_candidates(
    args: Any,
    paths: dict[str, Path],
    rows: list[dict[str, Any]],
    candidate_indexes: list[int],
    service: EnrichmentService,
    stop_requested: Callable[[], bool],
) -> tuple[str, str | None]:
    ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()
    ws_endpoint = facebook_runner.rewrite_cdp_endpoint_host(ws_endpoint, args.octo_host)
    append_event(
        paths["events"],
        {
            "at": facebook_runner.utc_now(),
            "kind": "started",
            "profile_uuid": facebook_runner.OCTO_PROFILE_UUID,
            "profile_country": facebook_runner.normalize_country(
                connection_data.get("country")
            ),
            "candidates": len(candidate_indexes),
        },
    )
    executor = PlaywrightRelevantAdExecutor(EnrichmentOptions.from_namespace(args))
    infrastructure_error = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        seen_targets: set[str] = set()
        for sequence, row_index in enumerate(candidate_indexes, start=1):
            if stop_requested():
                break
            row = rows[row_index]
            target_key = service.target_key(row)
            if target_key and target_key in seen_targets:
                row["enrichment"] = {
                    "status": "skipped_duplicate_candidate",
                    "active_actions_started": False,
                    "target_key": target_key,
                }
                continue
            if target_key:
                seen_targets.add(target_key)
            result = service.enrich_one(
                executor,
                context,
                row,
                sequence=sequence,
                run_dir=paths["run_dir"],
            )
            rows[row_index] = result.ad
            _record_candidate(paths, rows, row_index, result.details)
            if result.details.get("infrastructure_error"):
                infrastructure_error = result.details.get("error")
                break
        neutralize_context(context)
    status = (
        "interrupted"
        if stop_requested()
        else "infrastructure_error"
        if infrastructure_error
        else "completed"
    )
    return status, infrastructure_error


def _paths(args: Any) -> dict[str, Path]:
    run_dir = args.run_dir.expanduser().resolve()
    source = (
        args.source.expanduser().resolve()
        if args.source
        else run_dir / "ads.prefilter.json"
    )
    output = (
        args.output.expanduser().resolve()
        if args.output
        else run_dir / "ads.enriched.json"
    )
    return {
        "run_dir": run_dir,
        "source": source,
        "output": output,
        "summary": run_dir / "enrichment_summary.json",
        "events": run_dir / "enrichment_events.jsonl",
    }


def _configure_profile(args: Any) -> None:
    config = get_config()
    facebook_runner.OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    facebook_runner.OCTO_PROFILE_UUID = (
        args.octo_profile_uuid or config.facebook.octo_profile_uuid
    )
    facebook_runner.OCTO_HEADLESS = args.octo_headless


def _record_candidate(
    paths: dict[str, Path],
    rows: list[dict[str, Any]],
    row_index: int,
    details: dict[str, Any],
) -> None:
    append_event(
        paths["events"],
        {
            "at": facebook_runner.utc_now(),
            "kind": "candidate_finished",
            "row_index": row_index,
            **details,
        },
    )
    write_json(paths["output"], rows)


def _write_completed(
    paths: dict[str, Path],
    rows: list[dict[str, Any]],
    service: EnrichmentService,
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    write_json(paths["output"], rows)
    summary = service.summary(rows, status=status)
    if error:
        summary["error"] = error
    write_json(paths["summary"], summary)
    append_event(
        paths["events"],
        {"at": facebook_runner.utc_now(), "kind": "finished", **summary},
    )
    return summary


def _print_summary(summary: dict[str, Any], status: str) -> None:
    print(
        f"[enrichment] status={status} allowed={summary['allowed']} "
        f"active={summary['active_candidates']} "
        f"landings={summary['landing_resolved']} "
        f"videos={summary['videos_recorded']}",
        flush=True,
    )


def neutralize_context(context: Any) -> None:
    pages = list(context.pages)
    if not pages:
        return
    keep = pages[0]
    for page in pages[1:]:
        try:
            page.close(run_before_unload=False)
        except PlaywrightError:
            pass
    facebook_runner.neutralize_profile_pages(keep, context)
