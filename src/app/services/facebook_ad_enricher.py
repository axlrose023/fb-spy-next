"""Actively enrich only ads allowed by the passive Facebook relevance gate."""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time
import traceback
from dataclasses import fields
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.services import facebook_runner
from app.services.facebook.calibration import CalibrationTarget
from app.services.facebook.engagement import wait_for_saved_post
from app.settings import get_config

STOP_REQUESTED = False


def _request_stop(signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise KeyboardInterrupt(f"signal {signum}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    run_dir = args.run_dir.expanduser().resolve()
    source_path = (
        args.source.expanduser().resolve()
        if args.source
        else run_dir / "ads.prefilter.json"
    )
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else run_dir / "ads.enriched.json"
    )
    summary_path = run_dir / "enrichment_summary.json"
    events_path = run_dir / "enrichment_events.jsonl"

    if not source_path.exists():
        _write_json(summary_path, {
            "status": "no_prefilter_file",
            "source": str(source_path),
        })
        return 2

    rows = _load_ads(source_path)
    candidate_indexes = _candidate_indexes(rows)
    for row in rows:
        if row.get("relevance_gate") != "allow":
            row["enrichment"] = {
                "status": "blocked_by_relevance_gate",
                "active_actions_started": False,
            }

    if not candidate_indexes:
        _write_json(output_path, rows)
        summary = _summary(rows, status="completed")
        _write_json(summary_path, summary)
        print("[enrichment] no allowed candidates; no browser actions", flush=True)
        return 0

    config = get_config()
    profile_uuid = args.octo_profile_uuid or config.facebook.octo_profile_uuid
    facebook_runner.OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    facebook_runner.OCTO_PROFILE_UUID = profile_uuid
    facebook_runner.OCTO_HEADLESS = args.octo_headless

    try:
        ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()
        ws_endpoint = facebook_runner.rewrite_cdp_endpoint_host(
            ws_endpoint,
            args.octo_host,
        )
        _append_event(events_path, {
            "at": facebook_runner.utc_now(),
            "kind": "started",
            "profile_uuid": profile_uuid,
            "profile_country": facebook_runner.normalize_country(
                connection_data.get("country")
            ),
            "candidates": len(candidate_indexes),
        })
        seen_targets: set[str] = set()
        infrastructure_error = None
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(ws_endpoint)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            for sequence, row_index in enumerate(candidate_indexes, start=1):
                if STOP_REQUESTED:
                    break
                row = rows[row_index]
                target_key = _target_key(row)
                if target_key and target_key in seen_targets:
                    row["enrichment"] = {
                        "status": "skipped_duplicate_candidate",
                        "active_actions_started": False,
                        "target_key": target_key,
                    }
                    continue
                if target_key:
                    seen_targets.add(target_key)
                enriched, result = _enrich_one(
                    context,
                    row,
                    sequence=sequence,
                    run_dir=run_dir,
                    args=args,
                )
                rows[row_index] = enriched
                _append_event(events_path, {
                    "at": facebook_runner.utc_now(),
                    "kind": "candidate_finished",
                    "row_index": row_index,
                    **result,
                })
                _write_json(output_path, rows)
                if result.get("infrastructure_error"):
                    infrastructure_error = result.get("error")
                    break
            _neutralize_context(context)

        _write_json(output_path, rows)
        status = (
            "interrupted"
            if STOP_REQUESTED
            else "infrastructure_error"
            if infrastructure_error
            else "completed"
        )
        summary = _summary(rows, status=status)
        if infrastructure_error:
            summary["error"] = infrastructure_error
        _write_json(summary_path, summary)
        _append_event(
            events_path,
            {"at": facebook_runner.utc_now(), "kind": "finished", **summary},
        )
        if summary["active_actions_on_blocked_ads"]:
            print(
                "[enrichment invariant] active action reached a blocked ad",
                file=sys.stderr,
                flush=True,
            )
            return 4
        print(
            f"[enrichment] status={status} allowed={summary['allowed']} "
            f"active={summary['active_candidates']} "
            f"landings={summary['landing_resolved']} "
            f"videos={summary['videos_recorded']}",
            flush=True,
        )
        if STOP_REQUESTED:
            return 130
        return 2 if infrastructure_error else 0
    except KeyboardInterrupt:
        _write_json(output_path, rows)
        _write_json(summary_path, _summary(rows, status="interrupted"))
        return 130
    except Exception as exc:
        _write_json(output_path, rows)
        summary = _summary(rows, status="infrastructure_error")
        summary["error"] = repr(exc)
        summary["traceback"] = traceback.format_exc()
        _write_json(summary_path, summary)
        print(f"[enrichment error] {exc!r}", file=sys.stderr, flush=True)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--octo-host", default="127.0.0.1")
    parser.add_argument("--octo-port", type=int, default=58888)
    parser.add_argument("--octo-profile-uuid", default="")
    parser.add_argument("--octo-headless", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--locate-timeout-ms", type=int, default=12_000)
    parser.add_argument("--wait-after-load", type=float, default=2.0)
    parser.add_argument(
        "--record-videos",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--video-max-seconds", type=float, default=10.0)
    parser.add_argument(
        "--resolve-landings",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--landing-archive-timeout", type=float, default=20.0)
    parser.add_argument("--landing-archive-max-resources", type=int, default=120)
    return parser


def _enrich_one(
    context,
    raw: dict[str, Any],
    *,
    sequence: int,
    run_dir: Path,
    args,
) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched = dict(raw)
    post_url = _valid_post_url(raw.get("facebook_post_url"))
    result: dict[str, Any] = {
        "status": "pending",
        "active_actions_started": False,
        "post_url": post_url,
        "post_url_recovery": None,
        "video_attempted": False,
        "video_recorded": False,
        "cta_click_attempted": False,
        "landing_resolved": False,
        "error": None,
    }
    if raw.get("relevance_gate") != "allow":
        result["status"] = "blocked_by_relevance_gate"
        enriched["enrichment"] = result
        return enriched, result
    if not post_url:
        post_url, recovery = _recover_allowed_post_url(
            context,
            enriched,
            args=args,
        )
        result["post_url_recovery"] = recovery
        result["active_actions_started"] = bool(
            recovery.get("profile_navigation_started")
        )
        result["post_url"] = post_url
        if post_url:
            enriched["facebook_post_url"] = post_url
        else:
            result["status"] = "skipped_missing_passive_post_url"
            enriched["enrichment"] = result
            return enriched, result

    page = None
    started = time.monotonic()
    try:
        page = context.new_page()
        result["active_actions_started"] = True
        response = facebook_runner._goto_with_retry(
            page,
            post_url,
            timeout=max(1, args.timeout_ms),
            attempts=3,
        )
        if response and response.status >= 400:
            raise RuntimeError(
                f"saved Facebook post returned HTTP {response.status}"
            )
        if args.wait_after_load > 0:
            page.wait_for_timeout(round(args.wait_after_load * 1000))

        target = _target_from_raw(raw, post_url)
        located = wait_for_saved_post(
            page,
            target,
            timeout_ms=max(0, args.locate_timeout_ms),
        )
        result["match"] = located
        if located.get("status") != "located":
            raise RuntimeError(f"saved Facebook post not found: {located}")
        element_id = str(located["element_id"])
        ad = _ad_from_raw(raw, element_id=element_id)

        if args.record_videos and ad.has_video:
            result["video_attempted"] = True
            video_path = (
                run_dir
                / "videos"
                / f"{sequence:04d}_{_safe_slug(ad.advertiser or 'ad')}.mp4"
            )
            ok, issue = facebook_runner.record_ad_video(
                page,
                video_path,
                element_id,
                max_seconds=args.video_max_seconds,
            )
            result["video_recorded"] = ok
            result["video_issue"] = issue
            if ok:
                ad.video = str(video_path.relative_to(run_dir))

        if args.resolve_landings and ad.ad_type == "link" and ad.displayed_domain:
            result["cta_click_attempted"] = True
            timeout_seconds = max(
                30.0,
                args.landing_archive_timeout * 2 + 15.0,
            )
            with facebook_runner._hard_deadline(
                timeout_seconds,
                f"allowed landing enrichment: {ad.displayed_domain}",
            ):
                facebook_runner.resolve_in_view(
                    page,
                    context,
                    ad,
                    None,
                    element_id,
                    run_dir,
                    debug=None,
                    debug_id=sequence,
                    feed_url=post_url,
                    archive_landing=True,
                    landing_archive_timeout=args.landing_archive_timeout,
                    landing_archive_max_resources=args.landing_archive_max_resources,
                )
            result["landing_resolved"] = bool(ad.landing_full)

        for field in fields(facebook_runner.Ad):
            enriched[field.name] = getattr(ad, field.name)
        result["status"] = "completed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = repr(exc)
        result["infrastructure_error"] = _is_infrastructure_error(exc)
    finally:
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        if page is not None:
            facebook_runner._pause_ad_video(
                page,
                str(result.get("match", {}).get("element_id") or ""),
            )
            try:
                page.close(run_before_unload=False)
            except PlaywrightError:
                pass
    enriched["enrichment"] = result
    return enriched, result


def _recover_allowed_post_url(
    context,
    raw: dict[str, Any],
    *,
    args,
) -> tuple[str, dict[str, Any]]:
    """Recover one allowed ad from the neutralized collector page history."""
    recovery: dict[str, Any] = {
        "status": "pending",
        "profile_navigation_started": False,
        "matched_by": None,
        "media_guard": None,
        "error": None,
    }
    if raw.get("relevance_gate") != "allow":
        recovery["status"] = "blocked_by_relevance_gate"
        return "", recovery

    pages = list(getattr(context, "pages", []))
    page = next(
        (candidate for candidate in pages if candidate.url == "about:blank"),
        pages[0] if pages else None,
    )
    if page is None:
        recovery["status"] = "missing_profile_page"
        return "", recovery

    try:
        recovery["media_guard"] = facebook_runner.prepare_passive_media_guard(page)
        recovery["profile_navigation_started"] = True
        if page.url == "about:blank":
            page.go_back(
                wait_until="domcontentloaded",
                timeout=max(1, args.timeout_ms),
            )
        elif not _is_facebook_url(page.url):
            facebook_runner._goto_with_retry(
                page,
                "https://m.facebook.com/",
                timeout=max(1, args.timeout_ms),
                attempts=3,
            )
        facebook_runner.install_passive_media_guard(page)
        if args.wait_after_load > 0:
            page.wait_for_timeout(round(args.wait_after_load * 1000))

        element_id = str(raw.get("feed_element_id") or "")
        if element_id and _page_has_feed_element(page, element_id):
            recovery["matched_by"] = "preserved_feed_element_id"
        else:
            observed = _matching_visible_feed_row(
                page.evaluate(facebook_runner.DETECT_JS),
                raw,
            )
            if observed is None:
                recovery["status"] = "allowed_card_not_restored"
                return "", recovery
            element_id = str(observed.get("element_id") or "")
            recovery["matched_by"] = "strict_metadata"
            _merge_passive_identity(raw, observed)

        if not element_id:
            recovery["status"] = "missing_feed_element_id"
            return "", recovery
        ad = _ad_from_raw(raw, element_id=element_id)
        feed_url = page.url
        if not facebook_runner.resolve_facebook_post_url(
            page,
            ad,
            element_id,
            feed_url=feed_url,
        ):
            recovery["status"] = "permalink_not_resolved"
            return "", recovery
        post_url = _valid_post_url(ad.facebook_post_url)
        if not post_url:
            recovery["status"] = "invalid_recovered_post_url"
            return "", recovery
        raw["facebook_post_url"] = post_url
        raw["facebook_page_url"] = ad.facebook_page_url
        raw["fb_ad_id"] = ad.fb_ad_id
        recovery["status"] = "recovered"
        recovery["post_url"] = post_url
        return post_url, recovery
    except Exception as exc:
        recovery["status"] = "failed"
        recovery["error"] = repr(exc)
        return "", recovery
    finally:
        facebook_runner.neutralize_profile_pages(page, context)


def _page_has_feed_element(page, element_id: str) -> bool:
    try:
        return bool(page.evaluate(
            """
            elementId => Boolean(
              document.querySelector(`[data-fbspy-id="${elementId}"]`)
            )
            """,
            element_id,
        ))
    except Exception:
        return False


def _matching_visible_feed_row(
    rows: Any,
    expected: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    scored = [
        (_feed_row_match_score(row, expected), row)
        for row in rows
        if isinstance(row, dict)
    ]
    candidates = [
        (score, row)
        for score, row in scored
        if score >= 7 and row.get("element_id")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def _feed_row_match_score(
    observed: dict[str, Any],
    expected: dict[str, Any],
) -> int:
    expected_domain = _normalized_text(expected.get("displayed_domain"))
    observed_domain = _normalized_text(
        observed.get("domain") or observed.get("displayed_domain")
    )
    if expected_domain and observed_domain != expected_domain:
        return -1

    score = 4 if expected_domain else 0
    expected_advertiser = _normalized_text(expected.get("advertiser"))
    observed_advertiser = _normalized_text(observed.get("advertiser"))
    if expected_advertiser and expected_advertiser == observed_advertiser:
        score += 4

    expected_headline = _normalized_text(expected.get("headline"))
    observed_headline = _normalized_text(observed.get("headline"))
    if (
        expected_headline
        and observed_headline
        and (
            expected_headline.startswith(observed_headline)
            or observed_headline.startswith(expected_headline)
        )
    ):
        score += 3

    expected_creative = _url_path(expected.get("creative_img"))
    observed_creative = _url_path(observed.get("creative_img"))
    if expected_creative and expected_creative == observed_creative:
        score += 4

    expected_text = _normalized_text(expected.get("ad_text"))
    observed_text = _normalized_text(observed.get("ad_text"))
    if (
        expected_text
        and observed_text
        and (
            expected_text.startswith(observed_text)
            or observed_text.startswith(expected_text)
        )
    ):
        score += 2
    return score


def _merge_passive_identity(
    raw: dict[str, Any],
    observed: dict[str, Any],
) -> None:
    mapping = {
        "feed_element_id": "element_id",
        "displayed_domain": "domain",
        "facebook_post_url": "facebook_post_url",
        "facebook_page_url": "facebook_page_url",
        "fb_ad_id": "fb_ad_id",
        "cta_href": "cta_href",
    }
    for target, source in mapping.items():
        if not raw.get(target) and observed.get(source):
            raw[target] = observed[source]


def _normalized_text(value: Any) -> str:
    return " ".join(re.findall(r"\w+", str(value or "").casefold()))


def _url_path(value: Any) -> str:
    try:
        return urlparse(str(value or "")).path.casefold()
    except ValueError:
        return ""


def _is_facebook_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").casefold()
    except ValueError:
        return False
    return host == "facebook.com" or host.endswith(".facebook.com")


def _ad_from_raw(raw: dict[str, Any], *, element_id: str) -> facebook_runner.Ad:
    values = {
        field.name: raw.get(field.name)
        for field in fields(facebook_runner.Ad)
        if field.name in raw
    }
    values["advertiser"] = str(raw.get("advertiser") or "")
    values["ad_type"] = str(raw.get("ad_type") or "in_facebook")
    for name in (
        "displayed_domain",
        "headline",
        "ad_text",
        "cta",
        "cta_href",
        "creative_img",
        "video",
        "screenshot",
        "screenshot_issue",
    ):
        values[name] = str(raw.get(name) or "")
    values["has_video"] = bool(raw.get("has_video"))
    values["screenshot_ok"] = raw.get("screenshot_ok") is not False
    values["utm"] = raw.get("utm") if isinstance(raw.get("utm"), dict) else {}
    values["feed_element_id"] = element_id
    return facebook_runner.Ad(**values)


def _target_from_raw(raw: dict[str, Any], post_url: str) -> CalibrationTarget:
    return CalibrationTarget(
        url=post_url,
        advertiser=str(raw.get("advertiser") or ""),
        displayed_domain=str(raw.get("displayed_domain") or ""),
        headline=str(raw.get("headline") or ""),
        ad_text=str(raw.get("ad_text") or ""),
        cta=str(raw.get("cta") or ""),
        country=_clean(raw.get("country")),
        fb_ad_id=_clean(raw.get("fb_ad_id")),
        facebook_page_url=_clean(raw.get("facebook_page_url")),
        facebook_post_url=post_url,
        landing_clean=_clean(raw.get("landing_clean")),
        creative_img=_clean(raw.get("creative_img")),
    )


def _valid_post_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if "posts" in parts or parsed.path.rstrip("/").endswith(
        ("story.php", "permalink.php")
    ):
        return candidate
    return ""


def _target_key(raw: dict[str, Any]) -> str:
    return str(
        raw.get("facebook_post_url")
        or raw.get("fb_ad_id")
        or "\x1f".join(
            str(raw.get(key) or "").casefold()
            for key in ("advertiser", "displayed_domain", "headline", "ad_text")
        )
    ).strip("\x1f")


def _candidate_indexes(rows: list[dict[str, Any]]) -> list[int]:
    return [
        index
        for index, row in enumerate(rows)
        if row.get("relevance_gate") == "allow"
    ]


def _is_infrastructure_error(exc: Exception) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "Target page, context or browser has been closed",
            "BrowserContext.new_page: Target page, context or browser has been closed",
            "ERR_SOCKS_CONNECTION_FAILED",
            "ERR_PROXY_CONNECTION_FAILED",
            "ERR_NETWORK_CHANGED",
            "ERR_CONNECTION_RESET",
            "ERR_CONNECTION_CLOSED",
            "ERR_TIMED_OUT",
        )
    )


def _summary(rows: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    active_on_blocked = 0
    for row in rows:
        enrichment = row.get("enrichment")
        if (
            row.get("relevance_gate") != "allow"
            and isinstance(enrichment, dict)
            and enrichment.get("active_actions_started")
        ):
            active_on_blocked += 1
    enrichments = [
        row.get("enrichment")
        for row in rows
        if isinstance(row.get("enrichment"), dict)
    ]
    return {
        "status": status,
        "finished_at": facebook_runner.utc_now(),
        "total": len(rows),
        "allowed": sum(row.get("relevance_gate") == "allow" for row in rows),
        "blocked": sum(row.get("relevance_gate") != "allow" for row in rows),
        "active_candidates": sum(
            bool(item.get("active_actions_started")) for item in enrichments
        ),
        "landing_click_attempts": sum(
            bool(item.get("cta_click_attempted")) for item in enrichments
        ),
        "landing_resolved": sum(
            bool(item.get("landing_resolved")) for item in enrichments
        ),
        "video_attempts": sum(
            bool(item.get("video_attempted")) for item in enrichments
        ),
        "videos_recorded": sum(
            bool(item.get("video_recorded")) for item in enrichments
        ),
        "post_url_recovery_attempts": sum(
            isinstance(item.get("post_url_recovery"), dict)
            for item in enrichments
        ),
        "post_urls_recovered": sum(
            isinstance(item.get("post_url_recovery"), dict)
            and item["post_url_recovery"].get("status") == "recovered"
            for item in enrichments
        ),
        "active_actions_on_blocked_ads": active_on_blocked,
    }


def _neutralize_context(context) -> None:
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


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")[:32] or "ad"


def _clean(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _load_ads(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
