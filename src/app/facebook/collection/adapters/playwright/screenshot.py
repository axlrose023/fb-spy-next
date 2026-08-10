from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from app.facebook.feed import pause_all_videos

MEDIA_READY_JS = r"""
(elementId) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return false;
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width * r.height >= 25000 &&
      r.bottom > 0 && r.top < innerHeight &&
      s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity || 1) > 0.05;
  };
  const media = [...root.querySelectorAll("img,video")].filter(visible);
  if (!media.length) return true;
  return media.some(el => {
    if (el.tagName === "IMG") {
      return el.complete && el.naturalWidth > 50 && el.naturalHeight > 50;
    }
    if (el.tagName === "VIDEO") {
      return (el.readyState || 0) >= 2 ||
        (el.videoWidth > 50 && el.videoHeight > 50) ||
        !!el.poster;
    }
    return false;
  });
}
"""

VIDEO_CREATIVE_JS = r"""
(elementId) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return false;
  if (root.querySelector("video")) return true;
  for (const el of root.querySelectorAll('button,[role="button"],[aria-label],video')) {
    const cls = (typeof el.className === "string" ? el.className : "").toLowerCase();
    const label = (el.getAttribute("aria-label") || "").toLowerCase();
    if (cls.includes("inline-video-icon") || label.includes("video")) return true;
  }
  return false;
}
"""


def screenshot_has_blank_media(path: Path) -> bool:
    """Best-effort screenshot QA for a large blank media placeholder."""
    try:
        from PIL import Image
    except Exception:
        return False
    try:
        image = Image.open(path).convert("RGB")
    except Exception:
        return False
    width, height = image.size
    if width < 280 or height < 420:
        return False

    x0, x1 = int(width * 0.04), int(width * 0.96)
    y0 = max(80, int(height * 0.08))
    y1 = height - max(150, int(height * 0.18))
    if y1 - y0 < 180:
        return False

    crop = image.crop((x0, y0, x1, y1))
    sample_height = max(1, round(crop.height * 96 / max(1, crop.width)))
    content_sample = crop.resize((96, sample_height))
    content_pixels = cast(
        Iterable[tuple[int, int, int]],
        (
            content_sample.get_flattened_data()
            if hasattr(content_sample, "get_flattened_data")
            else content_sample.getdata()
        ),
    )
    total = saturated = 0
    for red, green, blue in content_pixels:
        total += 1
        average = (red + green + blue) / 3
        if max(red, green, blue) - min(red, green, blue) > 50 and average < 245:
            saturated += 1
    if total and saturated / total > 0.015:
        return False

    run = max_run = 0
    step = 16
    for y in range(y0, y1, step):
        band = image.crop((x0, y, x1, min(y + step, y1)))
        sample_height = max(1, round(band.height * 64 / max(1, band.width)))
        sample = band.resize((64, sample_height))
        pixels = cast(
            Iterable[tuple[int, int, int]],
            (
                sample.get_flattened_data()
                if hasattr(sample, "get_flattened_data")
                else sample.getdata()
            ),
        )
        total = 0
        light_neutral = dark = 0
        for red, green, blue in pixels:
            total += 1
            average = (red + green + blue) / 3
            if (
                average > 232 and max(red, green, blue) - min(red, green, blue) < 25
            ) or (red > 245 and green > 245 and blue > 245):
                light_neutral += 1
            if average < 120:
                dark += 1
        if total and light_neutral / total > 0.965 and dark / total < 0.003:
            run += band.height
        else:
            max_run = max(max_run, run)
            run = 0
    max_run = max(max_run, run)
    return max_run >= min(360, max(220, int(height * 0.32)))


def save_ad_screenshot(
    page: Any,
    path: Path,
    element_id: str | None,
    expect_media: bool = False,
    *,
    interest_safe: bool = False,
) -> bool:
    """Capture the exact ad element and fall back to the viewport if lost."""
    if element_id:
        locator = page.locator(f'[data-fbspy-id="{element_id}"]').first
        attempts = 1 if interest_safe else (2 if expect_media else 1)
        for attempt in range(attempts):
            try:
                locator.scroll_into_view_if_needed(timeout=5000)
                if interest_safe:
                    pause_all_videos(page)
                try:
                    page.wait_for_function(
                        MEDIA_READY_JS,
                        arg=element_id,
                        timeout=1200 if interest_safe else 3000 + attempt * 2000,
                    )
                except Exception:
                    pass
                time.sleep(0.15 if interest_safe else 0.5 + attempt * 1.0)
                box = locator.bounding_box(timeout=5000)
                if box and box.get("height", 0) <= 2600 and box.get("width", 0) <= 1200:
                    locator.screenshot(path=str(path), timeout=10000)
                    if (
                        expect_media
                        and attempt == 0
                        and screenshot_has_blank_media(path)
                    ):
                        print(f"  screenshot retry blank media {path.name}", flush=True)
                        continue
                    return True
            except Exception:
                pass
    try:
        page.screenshot(path=str(path))
        return False
    except Exception:
        return False


def has_video_creative(page: Any, element_id: str | None) -> bool:
    if not element_id:
        return False
    try:
        return bool(page.evaluate(VIDEO_CREATIVE_JS, element_id))
    except Exception:
        return False
