from __future__ import annotations

import subprocess
from pathlib import Path


def encode_video_frames(
    frames_dir: Path,
    output_path: Path,
    *,
    fps: float,
    ffmpeg: str,
) -> tuple[bool, str]:
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp.mp4")
    fps_arg = f"{max(1.0, float(fps)):.3f}".rstrip("0").rstrip(".")
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        fps_arg,
        "-start_number",
        "1",
        "-i",
        str(frames_dir / "frame_%05d.png"),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(tmp_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except Exception as exc:
        return False, repr(exc)
    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout or "ffmpeg_failed")[-1000:]
    tmp_path.replace(output_path)
    return output_path.exists() and output_path.stat().st_size > 0, "ok"
