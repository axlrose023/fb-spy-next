from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, UUID, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, DateTimeMixin, UUID7IDMixin

if TYPE_CHECKING:
    from app.api.modules.runs.models import FacebookRun


class FacebookAd(Base, UUID7IDMixin, DateTimeMixin):
    __tablename__ = "facebook_ads"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facebook_runs.id", ondelete="CASCADE"),
        index=True,
    )
    source_index: Mapped[int | None] = mapped_column(nullable=True)
    source_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    advertiser: Mapped[str] = mapped_column(String(512), index=True, default="")
    ad_type: Mapped[str] = mapped_column(String(32), index=True)
    format: Mapped[str] = mapped_column(String(32), index=True, default="image")
    vertical: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(64), index=True, default="facebook")
    placement: Mapped[str] = mapped_column(String(64), index=True, default="feed")
    cloaking: Mapped[bool | None] = mapped_column(Boolean, index=True, nullable=True)
    has_video: Mapped[bool] = mapped_column(Boolean, default=False)
    displayed_domain: Mapped[str] = mapped_column(String(512), index=True, default="")
    headline: Mapped[str] = mapped_column(Text, default="")
    ad_text: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(String(255), default="")
    creative_img: Mapped[str] = mapped_column(Text, default="")
    video_path: Mapped[str] = mapped_column(Text, default="")
    screenshot_path: Mapped[str] = mapped_column(Text, default="")
    screenshot_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    screenshot_issue: Mapped[str | None] = mapped_column(String(255), nullable=True)
    landing_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    landing_clean: Mapped[str | None] = mapped_column(Text, nullable=True)
    landing_screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    landing_archive_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    fb_ad_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    utm: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    run: Mapped[FacebookRun] = relationship("FacebookRun", back_populates="ads")
