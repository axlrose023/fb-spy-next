from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.facebook.collection import CollectedAd
from app.facebook.enrichment import EnrichmentOptions
from app.facebook.enrichment.adapters.playwright import video as video_adapter
from app.facebook.enrichment.video.adapters import playwright as video_capture
from app.facebook.enrichment.video.adapters.playwright import (
    encoder,
    frames,
    playback,
    recorder,
)
from app.services import facebook_runner

pytestmark = pytest.mark.unit


class VisibleElement:
    @property
    def first(self) -> VisibleElement:
        return self

    def scroll_into_view_if_needed(self, **_kwargs: object) -> None:
        pass


class RecordingPage:
    def locator(self, _selector: str) -> VisibleElement:
        return VisibleElement()


def test_runner_video_exports_are_canonical_aliases() -> None:
    assert facebook_runner.VIDEO_PREP_JS is video_capture.VIDEO_PREP_JS
    assert facebook_runner.record_ad_video is video_capture.record_ad_video
    assert facebook_runner._pause_ad_video is video_capture.pause_ad_video
    assert (
        facebook_runner._capture_screencast_frames
        is video_capture.capture_screencast_frames
    )
    assert (
        facebook_runner._write_screencast_frame is video_capture.write_screencast_frame
    )
    assert (
        facebook_runner._prepare_video_playback is video_capture.prepare_video_playback
    )
    assert facebook_runner._element_viewport_clip is video_capture.element_viewport_clip
    assert (
        facebook_runner._trim_static_tail_frames
        is video_capture.trim_static_tail_frames
    )
    assert facebook_runner._encode_video_frames is video_capture.encode_video_frames


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ({"x": 1, "y": 2, "width": 39, "height": 40}, None),
        (
            {
                "x": "1",
                "y": 2,
                "width": 40,
                "height": 50,
                "viewport_width": 0,
                "viewport_height": "100",
            },
            {
                "x": 1.0,
                "y": 2.0,
                "width": 40.0,
                "height": 50.0,
                "viewport_height": 100.0,
            },
        ),
    ],
)
def test_viewport_clip_normalization(
    value: object,
    expected: dict[str, float] | None,
) -> None:
    assert playback.normalize_viewport_clip(value) == expected


def test_recorder_always_pauses_and_removes_frames(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paused: list[str | None] = []
    output = tmp_path / "ad.mp4"
    monkeypatch.setattr(recorder.shutil, "which", lambda _name: "/ffmpeg")
    monkeypatch.setattr(
        recorder,
        "prepare_video_playback",
        lambda *_args: {"ok": True, "played": True, "duration": 2},
    )
    monkeypatch.setattr(
        recorder,
        "element_viewport_clip",
        lambda *_args: {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0},
    )
    monkeypatch.setattr(
        recorder,
        "capture_screencast_frames",
        lambda *_args, **_kwargs: (1, "capture_failed"),
    )
    monkeypatch.setattr(
        recorder, "pause_ad_video", lambda _page, value: paused.append(value)
    )

    result = recorder.record_ad_video(RecordingPage(), output, "ad-1")

    assert result == (False, "capture_failed")
    assert paused == ["ad-1"]
    assert not output.with_suffix(".mp4.frames").exists()


def test_static_tail_trimmer_removes_duplicate_tail(tmp_path: Path) -> None:
    for index in range(1, 13):
        Image.new("RGB", (80, 80), "white").save(tmp_path / f"frame_{index:05d}.png")

    kept = frames.trim_static_tail_frames(
        tmp_path,
        frame_count=12,
        fps=2,
        min_frames=2,
    )

    assert kept == 6
    assert (tmp_path / "frame_00006.png").exists()
    assert not (tmp_path / "frame_00007.png").exists()


def test_encoder_keeps_legacy_ffmpeg_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "recording.mp4"

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured.update(command=command, kwargs=kwargs)
        Path(command[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(encoder.subprocess, "run", run)

    result = encoder.encode_video_frames(
        tmp_path,
        output,
        fps=7.125,
        ffmpeg="/usr/bin/ffmpeg",
    )

    command = captured["command"]
    assert result == (True, "ok")
    assert isinstance(command, list)
    assert command[command.index("-framerate") + 1] == "7.125"
    assert "libx264" in command
    assert "+faststart" in command
    assert output.read_bytes() == b"video"


def test_enrichment_video_adapter_records_relative_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    ad = CollectedAd(advertiser="Demo Brand", ad_type="video", has_video=True)

    def record(
        _page: object,
        path: Path,
        element_id: str,
        **kwargs: object,
    ) -> tuple[bool, str]:
        captured.update(path=path, element_id=element_id, kwargs=kwargs)
        return True, "ok"

    monkeypatch.setattr(video_adapter, "record_ad_video", record)

    result = video_adapter.record_video(
        object(),
        ad,
        "element-1",
        sequence=3,
        run_dir=tmp_path,
        options=EnrichmentOptions(video_max_seconds=12),
    )

    assert result == (True, "ok")
    assert captured["path"] == tmp_path / "videos" / "0003_demo_brand.mp4"
    assert captured["element_id"] == "element-1"
    assert captured["kwargs"] == {"max_seconds": 12}
    assert ad.video == "videos/0003_demo_brand.mp4"
