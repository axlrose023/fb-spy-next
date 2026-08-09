from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Protocol

from .encoder import encode_video_frames
from .frames import trim_static_tail_frames
from .playback import element_viewport_clip, pause_ad_video, prepare_video_playback
from .screencast import capture_screencast_frames


class DebugEventSink(Protocol):
    def event(self, name: str, **fields: Any) -> None: ...


def record_ad_video(
    page: Any,
    path: Path,
    element_id: str | None,
    *,
    max_seconds: float = 30.0,
    fps: int = 8,
    debug: DebugEventSink | None = None,
    debug_id: int = 0,
) -> tuple[bool, str]:
    """Record the exact visible ad block as a visual-only MP4.

    CDP access to a running Octo profile cannot enable Playwright's native
    context recorder, while Facebook video sources are often blob-backed.
    Chrome's screencast stream also avoids repeated screenshot commands, which
    can wedge on animated posts. Frames are cropped to the ad and encoded with
    ffmpeg; audio is intentionally not captured.
    """
    if not element_id:
        return False, "missing_element_id"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg_not_found"

    fps = max(1, min(int(fps or 8), 20))
    max_seconds = max(1.0, min(float(max_seconds or 30.0), 45.0))
    loc = page.locator(f'[data-fbspy-id="{element_id}"]').first

    try:
        loc.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        return False, "element_not_visible"

    prep = prepare_video_playback(page, element_id)
    if not prep.get("ok"):
        return False, str(prep.get("reason") or "video_prepare_failed")
    if not prep.get("played"):
        try:
            page.mouse.click(int(prep.get("x") or 0), int(prep.get("y") or 0))
            time.sleep(0.5)
        except Exception:
            pass
        prep = prepare_video_playback(page, element_id)

    duration = prep.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        record_seconds = min(max_seconds, max(1.5, float(duration)))
    else:
        record_seconds = max_seconds

    clip = element_viewport_clip(page, element_id)
    if clip is None:
        return False, "element_clip_unavailable"

    path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = path.with_suffix(path.suffix + ".frames")
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    min_frames = max(2, min(fps * 2, 12))
    try:
        frame_count, last_error = capture_screencast_frames(
            page,
            frames_dir,
            clip=clip,
            record_seconds=record_seconds,
            fps=fps,
        )
        captured_frame_count = frame_count
        capture_elapsed = max(0.1, time.monotonic() - started)
        encode_fps = max(1.0, min(float(fps), captured_frame_count / capture_elapsed))
        trimmed_frames = 0
        if frame_count >= 2:
            trimmed_frame_count = trim_static_tail_frames(
                frames_dir,
                frame_count=frame_count,
                fps=fps,
                min_frames=min_frames,
            )
            trimmed_frames = frame_count - trimmed_frame_count
            frame_count = trimmed_frame_count

        if frame_count < 2:
            return False, last_error or "too_few_frames"
        ok, message = encode_video_frames(
            frames_dir,
            path,
            fps=encode_fps,
            ffmpeg=ffmpeg,
        )
        if ok and debug:
            debug.event(
                "video_recorded",
                debug_id=debug_id,
                path=str(path),
                frames=frame_count,
                fps=fps,
                encode_fps=round(encode_fps, 3),
                capture_seconds=round(capture_elapsed, 3),
                max_seconds=max_seconds,
                clip=clip,
                trimmed_frames=trimmed_frames,
                source_duration=duration,
            )
        return ok, message
    finally:
        pause_ad_video(page, element_id)
        shutil.rmtree(frames_dir, ignore_errors=True)
