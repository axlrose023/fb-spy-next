from __future__ import annotations

from typing import Any

from .scripts import VIDEO_PREP_JS


def pause_ad_video(page: Any, element_id: str | None) -> None:
    if not element_id:
        return
    try:
        page.evaluate(
            """
            elementId => {
              const root = document.querySelector(
                `[data-fbspy-id="${elementId}"]`
              );
              if (!root) return;
              for (const video of root.querySelectorAll("video")) {
                try { video.pause(); } catch (_) {}
              }
            }
            """,
            element_id,
        )
    except Exception:
        pass


def prepare_video_playback(page: Any, element_id: str) -> dict[str, Any]:
    try:
        data = page.evaluate(VIDEO_PREP_JS, element_id)
        return (
            data
            if isinstance(data, dict)
            else {"ok": False, "reason": "bad_video_prep"}
        )
    except Exception as exc:
        return {"ok": False, "reason": repr(exc)}


def element_viewport_clip(
    page: Any,
    element_id: str,
) -> dict[str, float] | None:
    try:
        clip = page.evaluate(
            r"""
            (elementId) => {
              const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
              if (!root) return null;
              const r = root.getBoundingClientRect();
              const x = Math.max(0, Math.floor(r.left));
              const y = Math.max(0, Math.floor(r.top));
              const right = Math.min(window.innerWidth, Math.ceil(r.right));
              const bottom = Math.min(window.innerHeight, Math.ceil(r.bottom));
              const width = right - x;
              const height = bottom - y;
              if (width < 40 || height < 40) return null;
              return {
                x,
                y,
                width,
                height,
                viewport_width: window.innerWidth,
                viewport_height: window.innerHeight,
              };
            }
            """,
            element_id,
        )
    except Exception:
        return None
    return normalize_viewport_clip(clip)


def normalize_viewport_clip(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value["width"])
        height = float(value["height"])
    except Exception:
        return None
    if width < 40 or height < 40:
        return None
    result = {"x": x, "y": y, "width": width, "height": height}
    for key in ("viewport_width", "viewport_height"):
        try:
            dimension = float(value[key])
        except Exception:
            continue
        if dimension > 0:
            result[key] = dimension
    return result
