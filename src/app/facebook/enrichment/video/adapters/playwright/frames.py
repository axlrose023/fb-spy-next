from __future__ import annotations

from pathlib import Path
from typing import Any


def trim_static_tail_frames(
    frames_dir: Path,
    *,
    frame_count: int,
    fps: int,
    min_frames: int,
) -> int:
    """Drop long duplicated tails left after a short video has ended."""
    if frame_count <= min_frames + fps * 2:
        return frame_count
    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception:
        return frame_count

    def signature(path: Path) -> Any:
        with Image.open(path) as image:
            resampling = getattr(Image, "Resampling", Image).BILINEAR
            return image.convert("L").resize((64, 64), resampling)

    def diff_score(left: Any, right: Any) -> float:
        stat = ImageStat.Stat(ImageChops.difference(left, right))
        return float(stat.mean[0])

    last_motion_frame = 1
    previous = None
    threshold = 0.45
    try:
        for index in range(1, frame_count + 1):
            current = signature(frames_dir / f"frame_{index:05d}.png")
            if previous is not None and diff_score(previous, current) > threshold:
                last_motion_frame = index
            previous = current
    except Exception:
        return frame_count

    tail_grace = max(fps, min_frames)
    min_keep_frames = max(min_frames, fps * 3)
    keep_frames = max(
        min_keep_frames,
        min(frame_count, last_motion_frame + tail_grace),
    )
    if frame_count - keep_frames < fps * 2:
        return frame_count
    for index in range(keep_frames + 1, frame_count + 1):
        try:
            (frames_dir / f"frame_{index:05d}.png").unlink()
        except FileNotFoundError:
            pass
    return keep_frames
