from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, DateTimeMixin, UUID7IDMixin


class FacebookRun(Base, UUID7IDMixin, DateTimeMixin):
    __tablename__ = "facebook_runs"

    status: Mapped[str] = mapped_column(String(32), index=True, default="created")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_minutes: Mapped[float] = mapped_column(default=10.0)
    collect_scrolls: Mapped[int] = mapped_column(Integer, default=10000)
    resolve_max: Mapped[int] = mapped_column(Integer, default=200)
    scroll_px: Mapped[int] = mapped_column(Integer, default=520)
    debug: Mapped[bool] = mapped_column(default=False)
    no_resolve: Mapped[bool] = mapped_column(default=False)
    no_shots: Mapped[bool] = mapped_column(default=False)
    octo_profile_uuid: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    profile_country: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    octo_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    out_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    runner_run_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    ads_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    debug_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    process_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_ads: Mapped[int] = mapped_column(Integer, default=0)
    link_ads: Mapped[int] = mapped_column(Integer, default=0)
    resolved_ads: Mapped[int] = mapped_column(Integer, default=0)
    video_ads: Mapped[int] = mapped_column(Integer, default=0)
    bad_screenshots: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ads: Mapped[list[Any]] = relationship(
        "FacebookAd",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
