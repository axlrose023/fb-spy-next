from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, TypeVar

from google import genai
from google.genai import types

from ..exceptions import (
    RelevanceProviderError,
    RelevanceProviderRateLimited,
    RelevanceProviderTimeout,
)

logger = logging.getLogger(__name__)

_GENERATE_TIMEOUT_S = 60
_HTTP_TIMEOUT_MS = 45_000
_UPLOAD_POLL_INTERVAL_S = 0.5
_UPLOAD_TIMEOUT_S = 60
_GENERATION_CONFIG = types.GenerateContentConfig(
    temperature=0,
    response_mime_type="application/json",
)
T = TypeVar("T")


class GeminiRelevanceProvider:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=_HTTP_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self._model = model

    async def generate_from_text(self, prompt: str) -> str:
        response = await self._generate(prompt)
        return response.text or ""

    async def generate_from_image(self, image_path: Path, prompt: str) -> str:
        image_data = await asyncio.to_thread(image_path.read_bytes)
        image = types.Part.from_bytes(
            data=image_data,
            mime_type=_guess_image_mime_type(image_path),
        )
        response = await self._generate([image, prompt])
        return response.text or ""

    async def generate_from_images(
        self,
        image_paths: list[Path],
        prompt: str,
    ) -> str:
        image_data = await asyncio.gather(
            *(asyncio.to_thread(path.read_bytes) for path in image_paths)
        )
        contents: list[Any] = []
        for index, (path, data) in enumerate(
            zip(image_paths, image_data, strict=True),
            start=1,
        ):
            contents.append(f"Image {index}: {path.name}")
            contents.append(
                types.Part.from_bytes(
                    data=data,
                    mime_type=_guess_image_mime_type(path),
                )
            )
        contents.append(prompt)
        response = await self._generate(contents)
        return response.text or ""

    async def generate_from_video(self, video_path: Path, prompt: str) -> str:
        uploaded = await self._await_provider(
            self._client.aio.files.upload(
                file=video_path,
                config=types.UploadFileConfig(
                    mime_type=_guess_video_mime_type(video_path),
                ),
            ),
            timeout=_UPLOAD_TIMEOUT_S,
        )
        try:
            uploaded = await self._wait_for_processing(uploaded)
            response = await self._generate([uploaded, prompt])
            return response.text or ""
        finally:
            await self._delete_file(uploaded)

    async def _generate(self, contents: Any) -> Any:
        return await self._await_provider(
            self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=_GENERATION_CONFIG,
            ),
            timeout=_GENERATE_TIMEOUT_S,
        )

    async def _wait_for_processing(self, uploaded: Any) -> Any:
        elapsed = 0.0
        while _file_state(uploaded) == "PROCESSING":
            if elapsed >= _UPLOAD_TIMEOUT_S:
                raise RelevanceProviderTimeout("Provider file processing timed out")
            await asyncio.sleep(_UPLOAD_POLL_INTERVAL_S)
            elapsed += _UPLOAD_POLL_INTERVAL_S
            uploaded = await self._await_provider(
                self._client.aio.files.get(name=uploaded.name),
                timeout=_UPLOAD_TIMEOUT_S,
            )
        if _file_state(uploaded) == "FAILED":
            raise RelevanceProviderError("Provider file processing failed")
        return uploaded

    async def _delete_file(self, uploaded: Any) -> None:
        try:
            await self._client.aio.files.delete(name=uploaded.name)
        except Exception:
            logger.warning("Failed to clean up relevance provider upload")

    @staticmethod
    async def _await_provider(awaitable: Awaitable[T], *, timeout: float) -> T:
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except TimeoutError:
            raise RelevanceProviderTimeout("Relevance provider timed out") from None
        except Exception as exc:
            message = str(exc).casefold()
            if "429" in message or "rate limit" in message or "resource_exhausted" in message:
                raise RelevanceProviderRateLimited(
                    "Relevance provider rate limit exceeded"
                ) from None
            raise RelevanceProviderError("Relevance provider request failed") from None


def _guess_image_mime_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _guess_video_mime_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".mov":
        return "video/quicktime"
    return "video/webm"


def _file_state(uploaded: Any) -> str:
    state = getattr(uploaded, "state", None)
    name = getattr(state, "name", None)
    value = name or getattr(state, "value", None) or state or ""
    return str(value).rsplit(".", 1)[-1].upper()
