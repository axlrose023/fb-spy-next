from pathlib import Path
from types import SimpleNamespace

import pytest

from app.clients import gemini


class FakeModels:
    def __init__(self) -> None:
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text="model response")


class FakeFiles:
    def __init__(self) -> None:
        self.uploaded = []
        self.deleted = []
        self.get_calls = 0

    async def upload(self, **kwargs):
        self.uploaded.append(kwargs)
        return SimpleNamespace(
            name="files/video",
            state=SimpleNamespace(name="PROCESSING"),
        )

    async def get(self, *, name):
        self.get_calls += 1
        return SimpleNamespace(
            name=name,
            state=SimpleNamespace(name="ACTIVE"),
        )

    async def delete(self, *, name):
        self.deleted.append(name)


class FakeClient:
    def __init__(self, *, api_key: str, http_options) -> None:
        self.api_key = api_key
        self.http_options = http_options
        self.models = FakeModels()
        self.files = FakeFiles()
        self.aio = SimpleNamespace(models=self.models, files=self.files)


@pytest.fixture
def fake_client(monkeypatch):
    created = []

    def factory(*, api_key: str, http_options):
        client = FakeClient(api_key=api_key, http_options=http_options)
        created.append(client)
        return client

    monkeypatch.setattr(gemini.genai, "Client", factory)
    monkeypatch.setattr(gemini, "_UPLOAD_POLL_INTERVAL_S", 0)
    return created


@pytest.mark.asyncio
async def test_generate_text_uses_async_google_genai_client(fake_client) -> None:
    client = gemini.GeminiClient("secret", "gemini-test")

    result = await client.generate_from_text("prompt")

    assert result == "model response"
    assert fake_client[0].api_key == "secret"
    assert fake_client[0].http_options.timeout == 45_000
    assert fake_client[0].http_options.retry_options.attempts == 1
    call = fake_client[0].models.calls[0]
    assert call["model"] == "gemini-test"
    assert call["contents"] == "prompt"
    assert call["config"].temperature == 0
    assert call["config"].response_mime_type == "application/json"


@pytest.mark.asyncio
async def test_generate_image_uses_inline_bytes(tmp_path: Path, fake_client) -> None:
    image_path = tmp_path / "creative.png"
    image_path.write_bytes(b"image-bytes")
    client = gemini.GeminiClient("secret")

    result = await client.generate_from_image(image_path, "inspect")

    assert result == "model response"
    contents = fake_client[0].models.calls[0]["contents"]
    assert contents[0].inline_data.data == b"image-bytes"
    assert contents[0].inline_data.mime_type == "image/png"
    assert contents[1] == "inspect"
    assert fake_client[0].models.calls[0]["config"].temperature == 0
    assert fake_client[0].files.uploaded == []


@pytest.mark.asyncio
async def test_generate_images_uses_all_inline_images(
    tmp_path: Path,
    fake_client,
) -> None:
    ad_path = tmp_path / "ad.png"
    landing_path = tmp_path / "landing.jpg"
    ad_path.write_bytes(b"ad-bytes")
    landing_path.write_bytes(b"landing-bytes")
    client = gemini.GeminiClient("secret")

    result = await client.generate_from_images([ad_path, landing_path], "inspect")

    assert result == "model response"
    call = fake_client[0].models.calls[0]
    contents = call["contents"]
    assert contents[0] == "Image 1: ad.png"
    assert contents[1].inline_data.data == b"ad-bytes"
    assert contents[1].inline_data.mime_type == "image/png"
    assert contents[2] == "Image 2: landing.jpg"
    assert contents[3].inline_data.data == b"landing-bytes"
    assert contents[3].inline_data.mime_type == "image/jpeg"
    assert contents[4] == "inspect"
    assert call["config"].temperature == 0


@pytest.mark.asyncio
async def test_generate_video_waits_and_deletes_uploaded_file(
    tmp_path: Path,
    fake_client,
) -> None:
    video_path = tmp_path / "creative.mp4"
    video_path.write_bytes(b"video-bytes")
    client = gemini.GeminiClient("secret")

    result = await client.generate_from_video(video_path, "inspect")

    assert result == "model response"
    files = fake_client[0].files
    assert files.uploaded[0]["file"] == video_path
    assert files.uploaded[0]["config"].mime_type == "video/mp4"
    assert files.get_calls == 1
    assert files.deleted == ["files/video"]
    contents = fake_client[0].models.calls[0]["contents"]
    assert contents[0].name == "files/video"
    assert contents[1] == "inspect"
    assert fake_client[0].models.calls[0]["config"].temperature == 0
