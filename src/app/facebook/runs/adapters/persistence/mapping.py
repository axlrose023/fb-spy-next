from __future__ import annotations

from ...models import NewRun, Run
from .models import FacebookRun


def to_domain(record: FacebookRun) -> Run:
    return Run(
        id=record.id,
        status=record.status,
        title=record.title,
        requested_minutes=record.requested_minutes,
        collect_scrolls=record.collect_scrolls,
        resolve_max=record.resolve_max,
        scroll_px=record.scroll_px,
        debug=record.debug,
        no_resolve=record.no_resolve,
        no_shots=record.no_shots,
        octo_profile_uuid=record.octo_profile_uuid,
        profile_country=record.profile_country,
        octo_ip=record.octo_ip,
        out_root=record.out_root,
        runner_run_dir=record.runner_run_dir,
        ads_json_path=record.ads_json_path,
        log_path=record.log_path,
        debug_dir=record.debug_dir,
        process_pid=record.process_pid,
        return_code=record.return_code,
        error=record.error,
        total_ads=record.total_ads,
        link_ads=record.link_ads,
        resolved_ads=record.resolved_ads,
        video_ads=record.video_ads,
        bad_screenshots=record.bad_screenshots,
        started_at=record.started_at,
        finished_at=record.finished_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_record(run: NewRun) -> FacebookRun:
    return FacebookRun(
        status=run.status,
        title=run.title,
        requested_minutes=run.requested_minutes,
        collect_scrolls=run.collect_scrolls,
        resolve_max=run.resolve_max,
        scroll_px=run.scroll_px,
        debug=run.debug,
        no_resolve=run.no_resolve,
        no_shots=run.no_shots,
        octo_profile_uuid=run.octo_profile_uuid,
        runner_run_dir=run.runner_run_dir,
        ads_json_path=run.ads_json_path,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )
