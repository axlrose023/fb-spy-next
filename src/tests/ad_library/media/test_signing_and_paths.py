from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.ad_library.media.exceptions import (
    MediaNotFoundError,
    MediaRangeError,
    MediaTokenError,
)
from app.ad_library.media.models import MediaKind
from app.ad_library.media.paths import LocalPathPolicy, ObjectKeyPolicy
from app.ad_library.media.ranges import resolve_local_range, validate_range_syntax
from app.ad_library.media.signing import MediaSigningPolicy, MediaURLSigner

pytestmark = pytest.mark.unit


def signer() -> MediaURLSigner:
    return MediaURLSigner(
        MediaSigningPolicy(
            secret="module-signing-secret-with-at-least-32-characters",
            ttl_seconds=300,
            public_path="/media",
        )
    )


def test_signed_url_contains_only_backend_proxy_coordinates() -> None:
    ad_id = uuid4()
    media_signer = signer()

    url = media_signer.url_for(
        ad_id,
        MediaKind.VIDEO,
        "s3:ads/private/object.mp4",
        now=1_900_000_000,
    )

    assert url is not None
    assert url.startswith(f"/media/ads/{ad_id}/video?token=")
    assert "s3:" not in url
    assert "private" not in url


@pytest.mark.parametrize(
    "public_path",
    ("media", "/", "//attacker.example/media", "/../media", "/media?next=x"),
)
def test_signing_policy_rejects_unsafe_public_paths(public_path: str) -> None:
    with pytest.raises(ValueError, match="safe absolute URL path"):
        MediaSigningPolicy(
            secret="module-signing-secret-with-at-least-32-characters",
            ttl_seconds=300,
            public_path=public_path,
        )


def test_token_is_bound_to_ad_kind_expiry_and_ttl_limit() -> None:
    media_signer = signer()
    ad_id = uuid4()
    now = 1_900_000_000
    token = media_signer.create_token(ad_id, MediaKind.SCREENSHOT, now=now)

    assert (
        media_signer.verify_token(
            token,
            ad_id,
            MediaKind.SCREENSHOT,
            now=now,
        )
        == now + 300
    )
    for candidate_id, kind, current in (
        (uuid4(), MediaKind.SCREENSHOT, now),
        (ad_id, MediaKind.VIDEO, now),
        (ad_id, MediaKind.SCREENSHOT, now + 301),
    ):
        with pytest.raises(MediaTokenError):
            media_signer.verify_token(token, candidate_id, kind, now=current)

    far_future = media_signer.create_token(
        ad_id,
        MediaKind.SCREENSHOT,
        now=now + 1_000,
    )
    with pytest.raises(MediaTokenError, match="configured limit"):
        media_signer.verify_token(
            far_future,
            ad_id,
            MediaKind.SCREENSHOT,
            now=now,
        )


def test_object_key_policy_builds_and_validates_exact_ad_layout() -> None:
    policy = ObjectKeyPolicy("ads")
    ad_id = uuid4()
    key = policy.build(ad_id, MediaKind.LANDING_SCREENSHOT, ".PNG")
    reference = policy.reference(key)

    assert key == f"ads/{ad_id}/screenshots/landing-full.png"
    assert (
        policy.key_for_read(
            reference,
            MediaKind.LANDING_SCREENSHOT,
            ad_id,
        )
        == key
    )
    assert policy.key_for_delete(reference) == key

    for invalid in (
        "s3:ads/../secret",
        "s3:ads//secret",
        f"s3:ads/{uuid4()}/screenshots/landing-full.png",
        f"s3:ads/{ad_id}/archives/landing.zip",
    ):
        with pytest.raises(MediaNotFoundError):
            policy.key_for_read(invalid, MediaKind.LANDING_SCREENSHOT, ad_id)


@pytest.mark.parametrize(
    "object_prefix",
    ("", "/", "ads//nested", "ads/../private", "ads\\private", "ads\x00private"),
)
def test_object_key_policy_rejects_unsafe_prefixes(object_prefix: str) -> None:
    with pytest.raises(ValueError, match="safe object path"):
        ObjectKeyPolicy(object_prefix)


def test_local_path_policy_rejects_parent_and_symlink_escape(tmp_path: Path) -> None:
    data_dir = tmp_path / "media"
    data_dir.mkdir()
    inside = data_dir / "inside.png"
    inside.write_bytes(b"image")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    link = data_dir / "link.png"
    link.symlink_to(outside)
    policy = LocalPathPolicy(data_dir)

    assert policy.resolve("inside.png") == inside.resolve()
    for reference in ("../outside.png", "link.png", "missing.png"):
        with pytest.raises(MediaNotFoundError):
            policy.resolve(reference)


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("bytes=0-3", 10, (0, 3)),
        ("bytes=4-", 10, (4, 9)),
        ("bytes=-4", 10, (6, 9)),
        ("bytes=0-99", 10, (0, 9)),
    ],
)
def test_range_policy_supports_standard_single_ranges(
    header: str,
    size: int,
    expected: tuple[int, int],
) -> None:
    validate_range_syntax(header)
    assert resolve_local_range(header, size) == expected


@pytest.mark.parametrize("header", ["bytes=", "items=0-1", "bytes=0-1,3-4"])
def test_range_policy_rejects_ambiguous_syntax(header: str) -> None:
    with pytest.raises(MediaRangeError):
        validate_range_syntax(header)
