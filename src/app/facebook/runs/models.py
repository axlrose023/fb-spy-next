from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Run:
    id: UUID
    status: str
    title: str | None
    requested_minutes: float
    collect_scrolls: int
    resolve_max: int
    scroll_px: int
    debug: bool
    no_resolve: bool
    no_shots: bool
    octo_profile_uuid: str | None
    profile_country: str | None
    octo_ip: str | None
    out_root: str | None
    runner_run_dir: str | None
    ads_json_path: str | None
    log_path: str | None
    debug_dir: str | None
    process_pid: int | None
    return_code: int | None
    error: str | None
    total_ads: int
    link_ads: int
    resolved_ads: int
    video_ads: int
    bad_screenshots: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NewRun:
    status: str = "created"
    title: str | None = None
    requested_minutes: float = 10.0
    collect_scrolls: int = 10000
    resolve_max: int = 200
    scroll_px: int = 520
    debug: bool = False
    no_resolve: bool = False
    no_shots: bool = False
    octo_profile_uuid: str | None = None
    runner_run_dir: str | None = None
    ads_json_path: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunDefaults:
    minutes: float
    collect_scrolls: int
    resolve_max: int
    scroll_px: int
    octo_profile_uuid: str | None


@dataclass(frozen=True, slots=True)
class StartRun:
    title: str | None = None
    octo_profile_uuid: str | None = None
    minutes: float | None = None
    collect_scrolls: int | None = None
    resolve_max: int | None = None
    scroll_px: int | None = None
    debug: bool = False
    no_resolve: bool = False
    no_shots: bool = False


@dataclass(frozen=True, slots=True)
class ImportRun:
    ads_json_path: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class RunQuery:
    page: int = 1
    page_size: int = 20
    status: str | None = None
    title_search: str | None = None
    octo_profile_uuid: str | None = None
    profile_country: str | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True, slots=True)
class RunPage:
    items: tuple[Run, ...]
    total: int
    page: int
    page_size: int
