from __future__ import annotations

import io
import urllib.error
from email.message import Message
from typing import Any

import pytest

from app.facebook.adapters import OctoApiError as PublicOctoApiError
from app.facebook.adapters.octo import (
    DEFAULT_OCTO_START_FLAGS,
    OctoActiveProfileSource,
    OctoApiError,
    OctoHttpClient,
    OctoLocalRuntime,
    OctoProfileSessionManager,
    OctoPublicProfileSource,
    rewrite_cdp_endpoint_host,
)
from app.facebook.profiles import ProfileSourceError
from app.services import facebook_runner

pytestmark = pytest.mark.unit


class RecordingTransport:
    def __init__(self, responses: list[dict[str, Any] | list[Any]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, dict[str, Any] | None, float | None]] = []

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | list[Any]:
        self.calls.append((method, path, body, timeout_seconds))
        return self._responses.pop(0)


class Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_public_source_paginates_deduplicates_and_drops_proxy_data() -> None:
    transport = RecordingTransport(
        [
            {
                "data": [
                    {
                        "uuid": "one",
                        "title": "One",
                        "proxy": {"password": "secret", "country": "TR"},
                    },
                    {"title": "missing uuid"},
                ],
                "total_count": 2,
            },
            {
                "data": [
                    {"uuid": "one", "title": "duplicate"},
                    {"uuid": "two", "title": "Two"},
                ],
                "total_count": 2,
            },
        ]
    )

    profiles = OctoPublicProfileSource(transport).discover(search_tags="fb ads")

    assert [(profile.octo_profile_uuid, profile.label) for profile in profiles] == [
        ("one", "One"),
        ("two", "Two"),
    ]
    assert all(profile.observed_country is None for profile in profiles)
    assert "search_tags=fb+ads" in transport.calls[0][1]
    assert "page=1" in transport.calls[1][1]
    assert "secret" not in repr(profiles)


def test_session_manager_restarts_wrong_mode_and_normalizes_connection() -> None:
    transport = RecordingTransport(
        [
            [
                {
                    "uuid": "profile",
                    "headless": False,
                    "ws_endpoint": "ws://127.0.0.1/visible",
                    "connection_data": {"country": "TR", "ip": "203.0.113.8"},
                }
            ],
            {"ok": True},
            {
                "ws_endpoint": "ws://127.0.0.1/headless",
                "connection_data": {"country": "TR", "ip": "203.0.113.8"},
            },
        ]
    )
    sleeps: list[float] = []
    sessions = OctoProfileSessionManager(
        transport,
        start_flags=["--no-sandbox"],
        sleeper=sleeps.append,
    )

    session = sessions.acquire("profile", headless=True)

    assert session.ws_endpoint.endswith("/headless")
    assert session.connection.country == "Turkey"
    assert session.connection.ip == "203.0.113.8"
    assert sleeps == [3, 2]
    assert transport.calls[1][:3] == (
        "POST",
        "/api/profiles/stop",
        {"uuid": "profile"},
    )
    assert transport.calls[2][2] == {
        "uuid": "profile",
        "headless": True,
        "debug_port": True,
        "flags": ["--no-sandbox"],
        "timeout": 120,
    }
    assert transport.calls[2][3] == 150


def test_local_runtime_acquires_configured_profile() -> None:
    transport = RecordingTransport(
        [
            [
                {
                    "uuid": "profile",
                    "headless": True,
                    "ws_endpoint": "ws://127.0.0.1/browser",
                    "connection_data": {
                        "country": "Canada",
                        "ip": "203.0.113.9",
                    },
                }
            ]
        ]
    )
    runtime = OctoLocalRuntime(
        "http://127.0.0.1:58888",
        "profile",
        headless=True,
        client=transport,
        sleeper=lambda _seconds: None,
    )

    session = runtime.acquire()

    assert session.ws_endpoint == "ws://127.0.0.1/browser"
    assert session.connection.country == "Canada"
    assert session.connection.ip == "203.0.113.9"
    assert transport.calls == [
        ("GET", "/api/profiles/active", None, None),
    ]


def test_local_runtime_maps_profile_source_error() -> None:
    class FailingTransport:
        def request(
            self,
            method: str,
            path: str,
            body: dict[str, Any] | None = None,
            *,
            timeout_seconds: float | None = None,
        ) -> dict[str, Any] | list[Any]:
            del method, path, body, timeout_seconds
            raise ProfileSourceError("redacted Octo failure")

    runtime = OctoLocalRuntime(
        "http://127.0.0.1:58888",
        "profile",
        client=FailingTransport(),
    )

    with pytest.raises(OctoApiError, match="redacted Octo failure") as captured:
        runtime.acquire()

    assert isinstance(captured.value.__cause__, ProfileSourceError)
    assert DEFAULT_OCTO_START_FLAGS == (
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--remote-debugging-address=0.0.0.0",
    )


def test_legacy_runner_reuses_canonical_octo_contracts() -> None:
    assert PublicOctoApiError is OctoApiError
    assert facebook_runner.OctoApiError is OctoApiError
    assert facebook_runner.OCTO_START_FLAGS == list(DEFAULT_OCTO_START_FLAGS)


def test_active_source_returns_safe_discovery_shape() -> None:
    transport = RecordingTransport(
        [
            [
                {
                    "uuid": "profile",
                    "title": "Canada",
                    "connection_data": {
                        "country": "Canada",
                        "ip": "203.0.113.9",
                        "proxy_password": "secret",
                    },
                }
            ]
        ]
    )
    source = OctoActiveProfileSource(
        OctoProfileSessionManager(transport, sleeper=lambda _seconds: None)
    )

    [profile] = source.discover()

    assert profile.octo_profile_uuid == "profile"
    assert profile.observed_country == "Canada"
    assert "203.0.113.9" not in repr(profile)
    assert "secret" not in repr(profile)


def test_http_errors_do_not_expose_token_url_or_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = urllib.error.HTTPError(
        "https://example.test/private?token=url-secret",
        401,
        "Unauthorized",
        Message(),
        io.BytesIO(b'proxy_password="body-secret"'),
    )
    monkeypatch.setattr(
        "app.facebook.adapters.octo.client.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    client = OctoHttpClient("https://example.test", token="header-secret")

    with pytest.raises(ProfileSourceError) as captured:
        client.request("GET", "/private")

    message = str(captured.value)
    assert message == "Octo API request failed with HTTP 401"
    assert captured.value.__cause__ is None
    assert all(
        secret not in message
        for secret in ("url-secret", "body-secret", "header-secret")
    )


def test_invalid_json_response_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.facebook.adapters.octo.client.urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(b'proxy_password="body-secret"'),
    )

    with pytest.raises(ProfileSourceError) as captured:
        OctoHttpClient("https://example.test", token="header-secret").request(
            "GET",
            "/profiles",
        )

    assert str(captured.value) == "Octo API returned an invalid JSON payload"
    assert captured.value.__cause__ is None
    assert "secret" not in str(captured.value)


def test_cdp_rewrite_preserves_non_local_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.facebook.adapters.octo.mapping.socket.gethostbyname",
        lambda _host: "192.0.2.4",
    )

    assert (
        rewrite_cdp_endpoint_host("ws://127.0.0.1:9000/browser", "remote-octo")
        == "ws://192.0.2.4:9000/browser"
    )
    assert (
        rewrite_cdp_endpoint_host("wss://octo.example/browser", "remote-octo")
        == "wss://octo.example/browser"
    )
