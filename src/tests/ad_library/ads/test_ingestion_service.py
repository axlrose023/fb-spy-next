from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.ad_library.ads import Ad
from app.ad_library.ads.ingestion import (
    AdIngestionRequest,
    AdIngestionService,
    AdMapper,
    AdMappingPolicy,
    AdSource,
)
from app.ad_library.media import MediaStorageError

pytestmark = pytest.mark.unit


class StubIngestionRepository:
    def __init__(self, existing: set[tuple[str, str]] | None = None) -> None:
        self.existing = existing or set()
        self.added: list[Ad] = []
        self.deleted: list[UUID] = []

    async def existing_identities(
        self,
        _identities: set[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        return set(self.existing)

    async def add_many(self, ads: Sequence[Ad]) -> None:
        self.added.extend(ads)

    async def delete_run_ads(self, run_id: UUID) -> None:
        self.deleted.append(run_id)


class RecordingMedia:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[list[str], bool]] = []

    async def upload_ads(
        self,
        ads: Sequence[Ad],
        *,
        relevance_verified: bool,
    ) -> int:
        self.calls.append(([ad.advertiser for ad in ads], relevance_verified))
        if self.fail:
            raise MediaStorageError("upload failed")
        return len(ads)


def mapper(data_dir: Path) -> AdMapper:
    return AdMapper(AdMappingPolicy(data_dir=data_dir, default_country="Turkey"))


def source(token: str, index: int, advertiser: str, fb_ad_id: str) -> AdSource:
    return AdSource(
        token=token,
        index=index,
        raw={
            "advertiser": advertiser,
            "ad_type": "link",
            "country": " Canada ",
            "fb_ad_id": fb_ad_id,
            "relevance": {"result": "relevant", "language": "English"},
        },
    )


async def test_ingestion_deduplicates_then_uploads_before_repository_write(
    tmp_path: Path,
) -> None:
    repository = StubIngestionRepository({("canada", "already-there")})
    media = RecordingMedia()
    service = AdIngestionService(repository, media, mapper(tmp_path))
    run_id = uuid4()
    request = AdIngestionRequest(
        run_id=run_id,
        run_dir=tmp_path,
        sources=[
            source("existing", 1, "Existing", "already-there"),
            source("first", 2, "First", "same-new-id"),
            source("duplicate", 3, "Duplicate", "same-new-id"),
            source("other", 4, "Other", "other-new-id"),
        ],
        replace_existing=True,
    )

    result = await service.ingest(request)

    assert repository.deleted == [run_id]
    assert [ad.advertiser for ad in result.observed] == [
        "Existing",
        "First",
        "Duplicate",
        "Other",
    ]
    assert [ad.advertiser for ad in repository.added] == ["First", "Other"]
    assert result.inserted_tokens == frozenset({"first", "other"})
    assert result.skipped_count == 2
    assert media.calls == [(["First", "Other"], True)]


async def test_ingestion_does_not_write_database_after_media_failure(
    tmp_path: Path,
) -> None:
    repository = StubIngestionRepository()
    media = RecordingMedia(fail=True)
    service = AdIngestionService(repository, media, mapper(tmp_path))

    with pytest.raises(MediaStorageError, match="upload failed"):
        await service.ingest(
            AdIngestionRequest(
                run_id=uuid4(),
                run_dir=tmp_path,
                sources=[source("one", 1, "One", "one")],
            )
        )

    assert repository.added == []


def test_mapper_preserves_geo_language_media_and_source_identity(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    raw = {
        "advertiser": "Mapped",
        "ad_type": "link",
        "has_video": True,
        "video": "videos/ad.mp4",
        "screenshot": "screens/ad.png",
        "fb_ad_id": " 123 ",
        "relevance": {"language": "Spanish"},
        "captured_at": "2026-08-07T10:00:00Z",
    }

    result = mapper(tmp_path).map(
        uuid4(),
        7,
        raw,
        run_dir,
        country_fallback="Spain",
    )

    assert result.country == "Spain"
    assert result.language == "es"
    assert result.format == "video"
    assert result.video_path == "run/videos/ad.mp4"
    assert result.screenshot_path == "run/screens/ad.png"
    assert result.fb_ad_id == "123"
    assert result.source_key == "fb_ad_id: 123 "
    assert result.captured_at is not None
