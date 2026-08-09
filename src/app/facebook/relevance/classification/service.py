from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..contracts import RelevanceProvider
from ..models import RelevanceResult
from .artifacts import existing_paths, first_existing_path
from .parser import parse_model_json
from .prefilter import apply_prefilter_uncertainty_guard
from .prompt import build_prompt
from .rules import apply_scope_guards

logger = logging.getLogger(__name__)

_BINARY_RESULTS = {"relevant", "not_relevant"}
_PREFILTER_RESULTS = {*_BINARY_RESULTS, "uncertain"}
_MAX_VIDEO_BYTES = 20 * 1024 * 1024


class RelevanceClassificationService:
    def __init__(
        self,
        provider: RelevanceProvider | None,
        *,
        enabled: bool,
    ) -> None:
        self._provider = provider
        self.enabled = enabled and provider is not None

    async def analyze(
        self,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        prefilter: bool = False,
    ) -> RelevanceResult:
        if not self.enabled or self._provider is None:
            return RelevanceResult(
                True,
                {"result": "relevant", "reason": "filter disabled"},
            )
        provider = self._provider

        video_result = await self._analyze_video(raw, run_dir, prefilter=prefilter)
        if video_result is not None and video_result.relevant:
            return video_result

        image_result = await self._analyze_images(raw, run_dir, prefilter=prefilter)
        if image_result is not None:
            return image_result

        response = await provider.generate_from_text(
            build_prompt(raw, vision=False, prefilter=prefilter)
        )
        return self._result(raw, response, "metadata", prefilter=prefilter)

    async def _analyze_video(
        self,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        prefilter: bool,
    ) -> RelevanceResult | None:
        provider = self._provider
        if provider is None:
            return None
        video_path = first_existing_path(run_dir, raw, ("video", "video_path"))
        if video_path is None or video_path.stat().st_size > _MAX_VIDEO_BYTES:
            return None
        try:
            response = await provider.generate_from_video(
                video_path,
                build_prompt(raw, vision=True, prefilter=prefilter),
            )
            return self._result(raw, response, "video", prefilter=prefilter)
        except Exception as exc:
            logger.warning(
                "FB relevance video analysis failed for %s: %s",
                video_path,
                exc,
            )
            return None

    async def _analyze_images(
        self,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        prefilter: bool,
    ) -> RelevanceResult | None:
        provider = self._provider
        if provider is None:
            return None
        image_paths = existing_paths(
            run_dir,
            raw,
            ("screenshot", "landing_screenshot"),
        )
        if len(image_paths) > 1:
            try:
                response = await provider.generate_from_images(
                    [path for _, path in image_paths],
                    build_prompt(
                        raw,
                        vision=True,
                        image_source="combined_screenshots",
                        prefilter=prefilter,
                    ),
                )
                return self._result(
                    raw,
                    response,
                    "combined_screenshots",
                    prefilter=prefilter,
                )
            except Exception as exc:
                logger.warning(
                    "FB relevance combined image analysis failed for %s: %s",
                    [path for _, path in image_paths],
                    exc,
                )

        last_result: RelevanceResult | None = None
        for source, image_path in image_paths:
            try:
                response = await provider.generate_from_image(
                    image_path,
                    build_prompt(
                        raw,
                        vision=True,
                        image_source=source,
                        prefilter=prefilter,
                    ),
                )
                last_result = self._result(
                    raw,
                    response,
                    source,
                    prefilter=prefilter,
                )
                if last_result.relevant:
                    return last_result
            except Exception as exc:
                logger.warning(
                    "FB relevance image analysis failed for %s: %s",
                    image_path,
                    exc,
                )
        return last_result

    @staticmethod
    def _result(
        raw: dict[str, Any],
        response: str,
        source: str,
        *,
        prefilter: bool,
    ) -> RelevanceResult:
        data = parse_model_json(
            response,
            allowed_results=_PREFILTER_RESULTS if prefilter else _BINARY_RESULTS,
        )
        data = apply_scope_guards(raw, data)
        if prefilter:
            data = apply_prefilter_uncertainty_guard(raw, data)
        return RelevanceResult(data["result"] == "relevant", data, response, source)
