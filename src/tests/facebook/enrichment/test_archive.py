from pathlib import Path

import httpx
import pytest

from app.facebook.enrichment import LandingArchiveResult
from app.facebook.enrichment.media.archive.policy import resource_rejection_reason

pytestmark = pytest.mark.unit


def _response(status: int, url: str, content_type: str) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"content-type": content_type},
        request=httpx.Request("GET", url),
    )


def test_resource_policy_rejects_error_documents() -> None:
    response = _response(200, "https://cdn.test/image.png", "text/html")

    reason = resource_rejection_reason(response, b"<html>404 not found</html>")

    assert reason == "error document"


def test_archive_result_requires_a_valid_zip(tmp_path: Path) -> None:
    path = tmp_path / "capture.zip"
    path.write_bytes(b"partial")

    result = LandingArchiveResult(path, "https://landing.test")

    assert result.ok is False
