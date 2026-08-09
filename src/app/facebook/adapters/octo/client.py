from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.facebook.profiles import ProfileSourceError


class OctoHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout_seconds: float = 40,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._headers = {"Content-Type": "application/json"}
        if token:
            self._headers["X-Octo-Api-Token"] = token

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | list[Any]:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers=self._headers,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds or self._timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raise ProfileSourceError(
                f"Octo API request failed with HTTP {exc.code}"
            ) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProfileSourceError(
                "Octo API returned an invalid JSON payload"
            ) from None
        except (OSError, TimeoutError, urllib.error.URLError):
            raise ProfileSourceError("Octo API request failed") from None
        if not isinstance(payload, (dict, list)):
            raise ProfileSourceError("Octo API returned an invalid JSON payload")
        return payload
