from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .models import RelevanceResult


class RelevanceAnalyzer(Protocol):
    async def analyze_raw_ad(
        self,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        prefilter: bool = False,
    ) -> RelevanceResult: ...


class RelevanceProvider(Protocol):
    async def generate_from_text(self, prompt: str) -> str: ...

    async def generate_from_image(self, image_path: Path, prompt: str) -> str: ...

    async def generate_from_images(
        self,
        image_paths: list[Path],
        prompt: str,
    ) -> str: ...

    async def generate_from_video(self, video_path: Path, prompt: str) -> str: ...
