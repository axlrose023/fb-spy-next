from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.ad_library.media.exceptions import MediaNotFoundError, MediaStorageError
from app.ad_library.media.models import MediaKind, MediaPayload
from app.ad_library.media.service import MediaService, MediaStorage

pytestmark = pytest.mark.unit


class StubSigner:
    def __init__(self) -> None:
        self.verified: list[tuple[str, UUID, MediaKind]] = []

    def url_for(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str | None,
        *,
        now: int | None = None,
    ) -> str | None:
        del ad_id, kind, now
        return stored_reference

    def verify_token(
        self,
        token: str,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> int:
        del now
        self.verified.append((token, ad_id, kind))
        return 0


class StubReferences:
    def __init__(self, reference: str | None) -> None:
        self.reference = reference

    async def reference_for(self, _ad_id: UUID, _kind: MediaKind) -> str | None:
        return self.reference


class StubAccess:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
        range_header: str | None = None,
    ) -> MediaPayload:
        del kind, ad_id
        self.calls.append(("open", range_header))
        return payload(stored_reference.encode())

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
    ) -> MediaPayload:
        del kind, ad_id
        self.calls.append(("head", None))
        return payload(stored_reference.encode())


class StubLocal:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def resolve(self, stored_reference: str) -> Path:
        return self.root / stored_reference

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        range_header: str | None,
    ) -> MediaPayload:
        del kind, range_header
        return payload(stored_reference.encode())

    async def head(self, stored_reference: str, kind: MediaKind) -> MediaPayload:
        del kind
        return payload(stored_reference.encode())


class StubRemote:
    def __init__(self) -> None:
        self.uploads: list[tuple[UUID, MediaKind, Path]] = []
        self.deleted: list[str] = []

    async def upload(self, ad_id: UUID, kind: MediaKind, source: Path) -> str:
        self.uploads.append((ad_id, kind, source))
        return f"s3:ads/{ad_id}/{kind.value}"

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
        range_header: str | None,
    ) -> MediaPayload:
        del kind, ad_id, range_header
        return payload(stored_reference.encode())

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
    ) -> MediaPayload:
        del kind, ad_id
        return payload(stored_reference.encode())

    async def delete(self, stored_reference: str) -> None:
        self.deleted.append(stored_reference)


@dataclass
class AdMedia:
    id: UUID
    screenshot_path: str | None = None
    landing_screenshot_path: str | None = None
    video_path: str | None = None
    landing_archive_path: str | None = None


def payload(data: bytes) -> MediaPayload:
    return MediaPayload(
        body=io.BytesIO(data),
        status_code=200,
        content_length=len(data),
        content_type="application/octet-stream",
    )


async def test_media_service_verifies_before_open_and_supports_head() -> None:
    ad_id = uuid4()
    signer = StubSigner()
    access = StubAccess()
    service = MediaService(StubReferences("media/file.mp4"), access, signer)

    opened = await service.get_media(
        ad_id,
        MediaKind.VIDEO,
        "token",
        range_header="bytes=0-1",
    )
    headed = await service.get_media(
        ad_id,
        MediaKind.VIDEO,
        "token",
        head_only=True,
    )

    assert opened.body.read() == b"media/file.mp4"
    assert headed.body.read() == b"media/file.mp4"
    assert signer.verified == [
        ("token", ad_id, MediaKind.VIDEO),
        ("token", ad_id, MediaKind.VIDEO),
    ]
    assert access.calls == [("open", "bytes=0-1"), ("head", None)]


async def test_media_service_hides_missing_ad_or_reference() -> None:
    with pytest.raises(MediaNotFoundError):
        await MediaService(
            StubReferences(None),
            StubAccess(),
            StubSigner(),
        ).get_media(uuid4(), MediaKind.SCREENSHOT, "token")


async def test_storage_uploads_only_local_references_after_relevance_gate(
    tmp_path: Path,
) -> None:
    local = StubLocal(tmp_path)
    remote = StubRemote()
    storage = MediaStorage(local, remote, backend="s3", upload_concurrency=2)
    ad = AdMedia(
        id=uuid4(),
        screenshot_path="screens/feed.png",
        video_path="s3:ads/already-uploaded/video.mp4",
    )

    with pytest.raises(MediaStorageError, match="relevance verification"):
        await storage.upload_ads([ad], relevance_verified=False)

    assert await storage.upload_ads([ad], relevance_verified=True) == 1
    assert ad.screenshot_path == f"s3:ads/{ad.id}/screenshot"
    assert len(remote.uploads) == 1


async def test_storage_routes_local_and_remote_references(tmp_path: Path) -> None:
    local = StubLocal(tmp_path)
    remote = StubRemote()
    storage = MediaStorage(local, remote, backend="s3", upload_concurrency=1)
    ad_id = uuid4()

    local_payload = await storage.open(
        "screens/feed.png",
        MediaKind.SCREENSHOT,
        ad_id=ad_id,
    )
    remote_payload = await storage.head(
        f"s3:ads/{ad_id}/screenshots/feed.png",
        MediaKind.SCREENSHOT,
        ad_id=ad_id,
    )
    await storage.delete_object(f"s3:ads/{ad_id}/screenshots/feed.png")

    assert local_payload.body.read() == b"screens/feed.png"
    assert remote_payload.body.read().startswith(b"s3:ads/")
    assert remote.deleted == [f"s3:ads/{ad_id}/screenshots/feed.png"]
