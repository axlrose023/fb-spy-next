import json
from pathlib import Path

import pytest

from app.facebook.relevance import RelevanceClassificationService, RelevanceService

pytestmark = pytest.mark.unit


class _Provider:
    def __init__(self) -> None:
        self.text = {"result": "not_relevant", "reason": "metadata"}
        self.video = {"result": "not_relevant", "reason": "video"}
        self.images = {"result": "relevant", "reason": "combined"}
        self.image = {"result": "not_relevant", "reason": "image"}
        self.calls: list[str] = []

    async def generate_from_text(self, _prompt: str) -> str:
        self.calls.append("text")
        return json.dumps(self.text)

    async def generate_from_video(self, _path: Path, _prompt: str) -> str:
        self.calls.append("video")
        return json.dumps(self.video)

    async def generate_from_images(self, _paths: list[Path], _prompt: str) -> str:
        self.calls.append("images")
        return json.dumps(self.images)

    async def generate_from_image(self, _path: Path, _prompt: str) -> str:
        self.calls.append("image")
        return json.dumps(self.image)


@pytest.mark.asyncio
async def test_non_relevant_video_falls_through_to_metadata(tmp_path: Path) -> None:
    video = tmp_path / "ad.mp4"
    video.write_bytes(b"video")
    provider = _Provider()
    provider.text = {
        "result": "relevant",
        "reason": "fake news finance prelander",
        "category": "other_relevant",
    }
    service = RelevanceClassificationService(provider, enabled=True)

    result = await service.analyze({"video": video.name}, tmp_path)

    assert result.relevant is True
    assert result.source == "metadata"
    assert provider.calls == ["video", "text"]


@pytest.mark.asyncio
async def test_combined_images_are_one_model_decision(tmp_path: Path) -> None:
    (tmp_path / "ad.png").touch()
    (tmp_path / "landing.png").touch()
    provider = _Provider()
    service = RelevanceClassificationService(provider, enabled=True)

    result = await service.analyze(
        {"screenshot": "ad.png", "landing_screenshot": "landing.png"},
        tmp_path,
    )

    assert result.relevant is True
    assert result.source == "combined_screenshots"
    assert provider.calls == ["images"]


@pytest.mark.asyncio
async def test_ordered_batch_decorates_without_mutating_inputs(tmp_path: Path) -> None:
    provider = _Provider()
    responses = iter(
        [
            {"result": "relevant", "reason": "target", "category": "trading"},
            {"result": "not_relevant", "reason": "shop"},
        ]
    )

    async def generate(_prompt: str) -> str:
        return json.dumps(next(responses))

    provider.generate_from_text = generate
    service = RelevanceService(
        RelevanceClassificationService(provider, enabled=True),
        concurrency=2,
    )
    rows = [{"advertiser": "Target"}, {"advertiser": "Shop"}]

    accepted, rejected = await service.filter_raw_ads(rows, tmp_path)

    assert [item["advertiser"] for item in accepted] == ["Target"]
    assert [item["advertiser"] for item in rejected] == ["Shop"]
    assert all("relevance" not in item for item in rows)
