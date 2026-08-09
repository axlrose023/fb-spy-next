from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.api.common.schema import Pagination, PaginationParams
from app.settings import get_config

from .models import ImportRun, Run, RunPage, RunQuery, StartRun


class RunStartRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    octo_profile_uuid: str | None = Field(default=None, min_length=1, max_length=64)
    minutes: float | None = Field(default=None, gt=0)
    collect_scrolls: int | None = Field(default=None, gt=0)
    resolve_max: int | None = Field(default=None, ge=0)
    scroll_px: int | None = Field(default=None, gt=0)
    debug: bool = False
    no_resolve: bool = False
    no_shots: bool = False

    model_config = ConfigDict(extra="forbid")


class RunImportRequest(BaseModel):
    ads_json_path: str = Field(..., min_length=1)
    title: str | None = Field(default=None, max_length=255)

    model_config = ConfigDict(extra="forbid")


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    title: str | None = None
    requested_minutes: float
    collect_scrolls: int
    resolve_max: int
    scroll_px: int
    debug: bool
    no_resolve: bool
    no_shots: bool
    octo_profile_uuid: str | None = None
    profile_country: str | None = None
    octo_ip: str | None = None
    out_root: str | None = None
    runner_run_dir: str | None = None
    ads_json_path: str | None = None
    log_path: str | None = None
    debug_dir: str | None = None
    process_pid: int | None = None
    return_code: int | None = None
    error: str | None = None
    total_ads: int
    link_ads: int
    resolved_ads: int
    video_ads: int
    bad_screenshots: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_url(self) -> str | None:
        if not self.log_path:
            return None
        mount = get_config().facebook.media_mount_path.rstrip("/")
        return f"{mount}/{self.log_path.lstrip('/')}"


class RunsPaginationResponse(Pagination[RunResponse]):
    model_config = ConfigDict(from_attributes=True)
    pass


class RunsPaginationParams(PaginationParams):
    status: str | None = None
    title__search: str | None = None
    octo_profile_uuid: str | None = None
    profile_country: str | None = None


def to_start_command(request: RunStartRequest) -> StartRun:
    return StartRun(
        title=request.title,
        octo_profile_uuid=request.octo_profile_uuid,
        minutes=request.minutes,
        collect_scrolls=request.collect_scrolls,
        resolve_max=request.resolve_max,
        scroll_px=request.scroll_px,
        debug=request.debug,
        no_resolve=request.no_resolve,
        no_shots=request.no_shots,
    )


def to_import_command(request: RunImportRequest) -> ImportRun:
    return ImportRun(ads_json_path=request.ads_json_path, title=request.title)


def to_query(params: RunsPaginationParams) -> RunQuery:
    return RunQuery(
        page=params.page,
        page_size=params.page_size,
        status=params.status,
        title_search=params.title__search,
        octo_profile_uuid=params.octo_profile_uuid,
        profile_country=params.profile_country,
    )


def to_response(run: Run) -> RunResponse:
    response: RunResponse = RunResponse.model_validate(run)
    return response


def to_page_response(page: RunPage) -> RunsPaginationResponse:
    return RunsPaginationResponse(
        total=page.total,
        items=[to_response(run) for run in page.items],
        page=page.page,
        page_size=page.page_size,
    )
