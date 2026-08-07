from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.api.common.schema import Pagination, PaginationParams
from app.settings import get_config


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

    @computed_field
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
