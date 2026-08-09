from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Any


def capture_screencast_frames(
    page: Any,
    frames_dir: Path,
    *,
    clip: dict[str, float],
    record_seconds: float,
    fps: int,
) -> tuple[int, str]:
    """Collect compositor frames without issuing Page.captureScreenshot."""
    client: Any = None
    started_stream = False
    interval = 1.0 / max(1, fps)
    state: dict[str, Any] = {
        "accepting": True,
        "frame_count": 0,
        "next_frame_at": time.monotonic(),
        "last_error": "",
    }

    def on_frame(event: dict[str, Any]) -> None:
        try:
            client.send(
                "Page.screencastFrameAck",
                {"sessionId": event["sessionId"]},
            )
        except Exception as exc:
            state["last_error"] = repr(exc)
            return
        if not state["accepting"]:
            return

        now = time.monotonic()
        if now < state["next_frame_at"]:
            return
        frame_number = int(state["frame_count"]) + 1
        frame_path = frames_dir / f"frame_{frame_number:05d}.png"
        ok, issue = write_screencast_frame(
            str(event.get("data") or ""),
            frame_path,
            clip=clip,
        )
        if not ok:
            state["last_error"] = issue
            return
        state["frame_count"] = frame_number
        next_frame_at = float(state["next_frame_at"]) + interval
        state["next_frame_at"] = max(next_frame_at, now + interval * 0.5)

    try:
        client = page.context.new_cdp_session(page)
        client.on("Page.screencastFrame", on_frame)
        client.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 80,
                "everyNthFrame": 1,
            },
        )
        started_stream = True
        page.wait_for_timeout(round(max(0.1, record_seconds) * 1000))
    except Exception as exc:
        state["last_error"] = repr(exc)
    finally:
        state["accepting"] = False
        if client is not None:
            if started_stream:
                try:
                    client.send("Page.stopScreencast")
                except Exception as exc:
                    if not state["last_error"]:
                        state["last_error"] = repr(exc)
            try:
                client.detach()
            except Exception:
                pass
    return int(state["frame_count"]), str(state["last_error"])


def write_screencast_frame(
    encoded_frame: str,
    path: Path,
    *,
    clip: dict[str, float],
) -> tuple[bool, str]:
    try:
        from PIL import Image

        payload = base64.b64decode(encoded_frame, validate=True)
        with Image.open(BytesIO(payload)) as source:
            image = source.convert("RGB")
            viewport_width = max(
                1.0,
                float(clip.get("viewport_width") or image.width),
            )
            viewport_height = max(
                1.0,
                float(clip.get("viewport_height") or image.height),
            )
            scale_x = image.width / viewport_width
            scale_y = image.height / viewport_height
            left = max(0, round(float(clip["x"]) * scale_x))
            top = max(0, round(float(clip["y"]) * scale_y))
            right = min(
                image.width,
                round((float(clip["x"]) + float(clip["width"])) * scale_x),
            )
            bottom = min(
                image.height,
                round((float(clip["y"]) + float(clip["height"])) * scale_y),
            )
            if right - left < 40 or bottom - top < 40:
                return False, "screencast_clip_too_small"
            image.crop((left, top, right, bottom)).save(path, format="PNG")
        return True, "ok"
    except Exception as exc:
        return False, repr(exc)
