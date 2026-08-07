import json
import os
import time
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.api.modules.runs.models import FacebookRun
from app.services import facebook_runner
from app.services.facebook.importer import FacebookAdsImporter
from app.services.facebook.runner_process import FacebookRunnerRegistry
from app.settings import Config, FacebookConfig, MediaStorageConfig


def test_runner_disables_playwright_font_wait() -> None:
    assert os.environ["PW_TEST_SCREENSHOT_NO_FONTS_READY"] == "1"


class FlakyNavigationPage:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    def goto(self, *_args, **_kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "loaded"


class FakeCDPSession:
    def __init__(self) -> None:
        self.commands = []

    def send(self, method, params) -> None:
        self.commands.append((method, params))


class FakeBrowserContext:
    def __init__(self) -> None:
        self.session = FakeCDPSession()

    def new_cdp_session(self, _page):
        return self.session


class ProxyCertificateNavigationPage(FlakyNavigationPage):
    def __init__(self) -> None:
        super().__init__([RuntimeError("net::ERR_CERT_AUTHORITY_INVALID")])
        self.context = FakeBrowserContext()


def test_goto_retries_transient_proxy_failure(monkeypatch) -> None:
    page = FlakyNavigationPage([
        RuntimeError("net::ERR_SOCKS_CONNECTION_FAILED"),
        RuntimeError("net::ERR_SOCKS_CONNECTION_FAILED"),
    ])
    delays = []
    monkeypatch.setattr(facebook_runner.time, "sleep", delays.append)

    result = facebook_runner._goto_with_retry(
        page,
        "https://m.facebook.com/",
        timeout=20_000,
    )

    assert result == "loaded"
    assert page.calls == 3
    assert delays == [1.5, 3.0]


def test_goto_retries_playwright_navigation_timeout(monkeypatch) -> None:
    page = FlakyNavigationPage([
        PlaywrightTimeoutError("Page.goto: Timeout 20000ms exceeded."),
    ])
    delays = []
    monkeypatch.setattr(facebook_runner.time, "sleep", delays.append)

    result = facebook_runner._goto_with_retry(
        page,
        "https://m.facebook.com/",
        timeout=20_000,
    )

    assert result == "loaded"
    assert page.calls == 2
    assert delays == [1.5]


def test_goto_does_not_retry_non_transient_failure(monkeypatch) -> None:
    page = FlakyNavigationPage([RuntimeError("net::ERR_CERT_INVALID")])
    monkeypatch.setattr(facebook_runner.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="ERR_CERT_INVALID"):
        facebook_runner._goto_with_retry(
            page,
            "https://m.facebook.com/",
            timeout=20_000,
        )

    assert page.calls == 1


def test_goto_accepts_proxy_certificate_authority_for_cdp_session() -> None:
    page = ProxyCertificateNavigationPage()

    result = facebook_runner._goto_with_retry(
        page,
        "https://m.facebook.com/",
        timeout=20_000,
    )

    assert result == "loaded"
    assert page.calls == 2
    assert page.context.session.commands == [
        ("Security.setIgnoreCertificateErrors", {"ignore": True})
    ]


class FacebookSessionPage:
    def __init__(self, login_required: bool) -> None:
        self.login_required = login_required
        self.url = "https://m.facebook.com/"

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url

    def evaluate(self, _script):
        return self.login_required


def test_facebook_login_required_probe_detects_logged_out_page() -> None:
    assert facebook_runner._facebook_login_required(
        FacebookSessionPage(login_required=True)
    )
    assert not facebook_runner._facebook_login_required(
        FacebookSessionPage(login_required=False)
    )


class PassiveGuardPage:
    def __init__(self) -> None:
        self.init_scripts = []
        self.route_handler = None

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def route(self, _pattern: str, handler) -> None:
        self.route_handler = handler


class PassiveGuardRoute:
    def __init__(self, resource_type: str) -> None:
        self.request = type("Request", (), {"resource_type": resource_type})()
        self.action = None

    def abort(self) -> None:
        self.action = "abort"

    def continue_(self) -> None:
        self.action = "continue"


def test_passive_media_guard_is_ready_before_navigation() -> None:
    page = PassiveGuardPage()

    stats = facebook_runner.prepare_passive_media_guard(page)

    assert stats["init_script_installed"] is True
    assert stats["media_route_installed"] is True
    assert "HTMLMediaElement.prototype.play" in page.init_scripts[0]

    media = PassiveGuardRoute("media")
    image = PassiveGuardRoute("image")
    page.route_handler(media)
    page.route_handler(image)

    assert media.action == "abort"
    assert image.action == "continue"
    assert stats["blocked_media_requests"] == 1


def test_collect_stops_logged_out_profile_without_counting_empty_feed(
    tmp_path,
    monkeypatch,
) -> None:
    page = FacebookSessionPage(login_required=True)
    monkeypatch.setattr(facebook_runner.time, "sleep", lambda _seconds: None)

    ads = facebook_runner.collect(
        page,
        object(),
        tmp_path,
        minutes=15,
        max_scrolls=100,
        shots=False,
        do_resolve=False,
        resolve_max=0,
        scroll_px=520,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert ads == {}
    assert summary["stop_reason"] == "facebook_login_required"
    assert summary["facebook_login_required"] is True
    assert summary["scrolls"] == 0


def test_interest_safe_collect_overrides_all_active_flags(
    tmp_path,
    monkeypatch,
) -> None:
    page = FacebookSessionPage(login_required=True)
    monkeypatch.setattr(facebook_runner.time, "sleep", lambda _seconds: None)

    facebook_runner.collect(
        page,
        object(),
        tmp_path,
        minutes=1,
        max_scrolls=1,
        shots=False,
        do_resolve=True,
        resolve_max=10,
        scroll_px=520,
        record_videos=True,
        resolve_post_urls=True,
        interest_safe_mode=True,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["resolve_enabled"] is False
    assert summary["interest_safe_overrides"] == [
        "landing_resolution",
        "video_recording",
        "permalink_resolution",
    ]
    assert summary["active_actions"] == {
        "cta_click_attempts": 0,
        "video_play_attempts": 0,
        "comment_open_attempts": 0,
    }


def test_octo_proxy_start_failure_writes_machine_readable_metrics(tmp_path) -> None:
    reason = facebook_runner._write_octo_start_failure(
        tmp_path,
        profile_uuid="profile-uuid",
        octo_host="host.docker.internal",
        octo_port=58888,
        octo_headless=False,
        requested_minutes=15,
        started_at="2026-07-17T06:00:00+00:00",
        elapsed_seconds=1.25,
        error=facebook_runner.OctoApiError(
            'HTTP 400 {"code":"profiles.proxy_error"}'
        ),
    )

    meta = json.loads((tmp_path / "run_meta.json").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert reason == "octo_proxy_error"
    assert meta["octo_profile_uuid"] == "profile-uuid"
    assert meta["start_failure"] == "octo_proxy_error"
    assert summary["stop_reason"] == "octo_proxy_error"
    assert summary["scrolls"] == 0
    assert summary["elapsed_seconds"] == pytest.approx(1.25)


@pytest.mark.parametrize("reason", ["resolve_timeout", "video_timeout"])
def test_browser_operation_timeout_uses_successful_fast_exit(
    tmp_path,
    monkeypatch,
    reason,
) -> None:
    (tmp_path / "summary.json").write_text(
        json.dumps({"stop_reason": reason}),
        encoding="utf-8",
    )
    exit_codes = []
    monkeypatch.setattr(facebook_runner.os, "_exit", exit_codes.append)

    facebook_runner._fast_exit_after_browser_operation_timeout(tmp_path)

    assert exit_codes == [0]


def test_normal_stop_reason_does_not_use_fast_exit(tmp_path, monkeypatch) -> None:
    (tmp_path / "summary.json").write_text(
        json.dumps({"stop_reason": "time_budget"}),
        encoding="utf-8",
    )
    exit_codes = []
    monkeypatch.setattr(facebook_runner.os, "_exit", exit_codes.append)

    facebook_runner._fast_exit_after_browser_operation_timeout(tmp_path)

    assert exit_codes == []


class StaticAdPage:
    def __init__(self) -> None:
        self.url = "https://m.facebook.com/"
        self.keyboard = self

    def evaluate(self, _script, _payload):
        self.url = "https://m.facebook.com/story.php?story_fbid=200&id=100"
        return {"status": "clicked", "label": "comment"}

    def wait_for_timeout(self, _timeout: int) -> None:
        pass

    def go_back(self, **_kwargs) -> None:
        self.url = "https://m.facebook.com/"

    def press(self, _key: str) -> None:
        pass


class ResolveTimeoutPage:
    url = "https://m.facebook.com/"

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url

    def evaluate(self, script, *_args):
        if script != facebook_runner.DETECT_JS:
            raise AssertionError("unexpected page evaluation")
        return [{
            "advertiser": "Saved before click",
            "ad_type": "link",
            "has_video": False,
            "domain": "blocked.example",
            "headline": "Headline",
            "ad_text": "Text",
            "cta": "Learn more",
            "creative_img": "https://cdn.example/image.jpg",
            "element_id": "ad-1",
            "fb_ad_id": None,
            "facebook_page_url": None,
            "facebook_post_url": None,
        }]


class VideoTimeoutPage(ResolveTimeoutPage):
    def evaluate(self, script, *_args):
        rows = super().evaluate(script)
        rows[0]["ad_type"] = "video"
        rows[0]["has_video"] = True
        return rows


class ImmediateDeadline:
    def __enter__(self):
        raise facebook_runner._OperationDeadlineExceeded("blocked landing")

    def __exit__(self, *_args) -> None:
        pass


class PartialVideoLocator:
    @property
    def first(self):
        return self

    def scroll_into_view_if_needed(self, **_kwargs) -> None:
        pass


class FakeScreencastSession:
    def __init__(self) -> None:
        self.handler = None
        self.started = False
        self.stopped = False
        self.detached = False
        self.acks = 0

    def on(self, event: str, handler) -> None:
        assert event == "Page.screencastFrame"
        self.handler = handler

    def send(self, method: str, payload=None) -> None:
        if method == "Page.startScreencast":
            self.started = True
        elif method == "Page.stopScreencast":
            self.stopped = True
        elif method == "Page.screencastFrameAck":
            self.acks += 1
        else:
            raise AssertionError(f"unexpected CDP method: {method}")

    def detach(self) -> None:
        self.detached = True


class FakeScreencastContext:
    def __init__(self, session: FakeScreencastSession) -> None:
        self.session = session

    def new_cdp_session(self, _page):
        return self.session


class ScreencastVideoPage:
    def __init__(self) -> None:
        self.locator_instance = PartialVideoLocator()
        self.session = FakeScreencastSession()
        self.context = FakeScreencastContext(self.session)

    def locator(self, _selector: str):
        return self.locator_instance

    def wait_for_timeout(self, _milliseconds: int) -> None:
        assert self.session.handler is not None
        for index in range(3):
            if index:
                time.sleep(0.06)
            image = Image.new("RGB", (120, 120), (index * 40, 80, 120))
            buffer = BytesIO()
            image.save(buffer, format="JPEG")
            self.session.handler({
                "data": facebook_runner.base64.b64encode(buffer.getvalue()).decode(),
                "sessionId": index + 1,
            })


def test_hard_deadline_interrupts_blocking_resolve_work() -> None:
    started = time.monotonic()

    with pytest.raises(facebook_runner._OperationDeadlineExceeded):
        with facebook_runner._hard_deadline(0.05, "test resolve"):
            time.sleep(5)

    assert time.monotonic() - started < 1


def test_resolve_timeout_saves_ad_and_ends_cycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        facebook_runner,
        "_hard_deadline",
        lambda *_args, **_kwargs: ImmediateDeadline(),
    )
    monkeypatch.setattr(facebook_runner.time, "sleep", lambda _seconds: None)

    ads = facebook_runner.collect(
        ResolveTimeoutPage(),
        object(),
        tmp_path,
        minutes=1,
        max_scrolls=10,
        shots=False,
        do_resolve=True,
        resolve_max=10,
        scroll_px=520,
        archive_landings=False,
        landing_archive_timeout=1,
        record_videos=False,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    partial = json.loads((tmp_path / "ads.partial.json").read_text(encoding="utf-8"))
    assert len(ads) == 1
    assert len(partial) == 1
    assert summary["stop_reason"] == "resolve_timeout"
    assert summary["resolve_timeouts"] == 1


def test_video_timeout_saves_ad_and_ends_cycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        facebook_runner,
        "_hard_deadline",
        lambda *_args, **_kwargs: ImmediateDeadline(),
    )
    monkeypatch.setattr(facebook_runner.time, "sleep", lambda _seconds: None)

    ads = facebook_runner.collect(
        VideoTimeoutPage(),
        object(),
        tmp_path,
        minutes=1,
        max_scrolls=10,
        shots=False,
        do_resolve=False,
        resolve_max=10,
        scroll_px=520,
        archive_landings=False,
        record_videos=True,
        video_max_seconds=10,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    partial = json.loads((tmp_path / "ads.partial.json").read_text(encoding="utf-8"))
    assert len(ads) == 1
    assert len(partial) == 1
    assert summary["stop_reason"] == "video_timeout"
    assert summary["video_timeouts"] == 1


def test_video_uses_screencast_frames_without_screenshot_commands(
    tmp_path,
    monkeypatch,
) -> None:
    page = ScreencastVideoPage()
    output_path = tmp_path / "video.mp4"
    encoded: dict[str, object] = {}
    monkeypatch.setattr(facebook_runner.shutil, "which", lambda _name: "/ffmpeg")
    monkeypatch.setattr(
        facebook_runner,
        "_prepare_video_playback",
        lambda *_args: {"ok": True, "played": True, "duration": 1},
    )
    monkeypatch.setattr(
        facebook_runner,
        "_element_viewport_clip",
        lambda *_args: {"x": 0, "y": 0, "width": 100, "height": 100},
    )
    monkeypatch.setattr(
        facebook_runner,
        "_trim_static_tail_frames",
        lambda _frames_dir, *, frame_count, **_kwargs: frame_count,
    )

    def fake_encode(frames_dir, path, *, fps, ffmpeg):
        encoded.update(path=path, fps=fps, ffmpeg=ffmpeg)
        assert (frames_dir / "frame_00001.png").exists()
        assert (frames_dir / "frame_00002.png").exists()
        assert (frames_dir / "frame_00003.png").exists()
        return True, "ok"

    monkeypatch.setattr(facebook_runner, "_encode_video_frames", fake_encode)

    ok, issue = facebook_runner.record_ad_video(
        page,
        output_path,
        "ad-1",
        max_seconds=1,
        fps=20,
    )

    assert (ok, issue) == (True, "ok")
    assert page.session.started is True
    assert page.session.stopped is True
    assert page.session.detached is True
    assert page.session.acks == 3
    assert encoded["path"] == output_path
    assert encoded["ffmpeg"] == "/ffmpeg"


def test_write_screencast_frame_crops_to_element(tmp_path) -> None:
    source = Image.new("RGB", (200, 100), "white")
    buffer = BytesIO()
    source.save(buffer, format="JPEG")
    output = tmp_path / "frame.png"

    ok, issue = facebook_runner._write_screencast_frame(
        facebook_runner.base64.b64encode(buffer.getvalue()).decode(),
        output,
        clip={
            "x": 25,
            "y": 10,
            "width": 50,
            "height": 40,
            "viewport_width": 100,
            "viewport_height": 50,
        },
    )

    assert (ok, issue) == (True, "ok")
    with Image.open(output) as cropped:
        assert cropped.size == (100, 80)


def test_runner_registry_command_uses_run_profile_and_exact_run_dir(tmp_path) -> None:
    config = Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        ),
        facebook=FacebookConfig(
            data_dir=tmp_path,
            runner_out_dir=tmp_path / "runs",
            octo_profile_uuid="default-profile",
        ),
    )
    registry = FacebookRunnerRegistry(config, FacebookAdsImporter(config))
    run = FacebookRun(
        id=uuid4(),
        status="created",
        octo_profile_uuid="run-profile",
        requested_minutes=1.0,
        collect_scrolls=5,
        resolve_max=2,
        scroll_px=520,
    )
    run_dir = tmp_path / "runs" / "run-custom"

    command = registry._command(run, run_dir)

    profile_arg = command.index("--octo-profile-uuid")
    run_dir_arg = command.index("--run-dir")
    assert command[profile_arg + 1] == "run-profile"
    assert Path(command[run_dir_arg + 1]) == run_dir
    assert "--out" not in command


def test_get_cdp_endpoint_uses_matching_active_profile(monkeypatch) -> None:
    monkeypatch.setattr(facebook_runner, "OCTO_PROFILE_UUID", "target-profile")

    def fake_octo(method, path, body=None):
        assert method == "GET"
        assert path == "/api/profiles/active"
        assert body is None
        return [
            {
                "uuid": "other-profile",
                "ws_endpoint": "ws://127.0.0.1:1111/devtools/browser/other",
                "connection_data": {"country": "Germany"},
            },
            {
                "uuid": "target-profile",
                "ws_endpoint": "ws://127.0.0.1:2222/devtools/browser/target",
                "connection_data": {"country": "France", "ip": "203.0.113.10"},
            },
        ]

    monkeypatch.setattr(facebook_runner, "octo", fake_octo)

    ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()

    assert ws_endpoint == "ws://127.0.0.1:2222/devtools/browser/target"
    assert connection_data == {"country": "France", "ip": "203.0.113.10"}


def test_get_cdp_endpoint_starts_requested_profile_when_not_active(monkeypatch) -> None:
    monkeypatch.setattr(facebook_runner, "OCTO_PROFILE_UUID", "target-profile")
    monkeypatch.setattr(facebook_runner.time, "sleep", lambda _seconds: None)
    calls = []

    def fake_octo(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET" and path == "/api/profiles/active":
            return [
                {
                    "uuid": "other-profile",
                    "ws_endpoint": "ws://127.0.0.1:1111/devtools/browser/other",
                },
            ]
        assert method == "POST"
        assert path == "/api/profiles/start"
        assert body["uuid"] == "target-profile"
        return {
            "ws_endpoint": "ws://127.0.0.1:2222/devtools/browser/target",
            "connection_data": {"country": "France", "ip": "203.0.113.10"},
        }

    monkeypatch.setattr(facebook_runner, "octo", fake_octo)

    ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()

    assert ws_endpoint == "ws://127.0.0.1:2222/devtools/browser/target"
    assert connection_data["country"] == "France"
    assert calls[1][2]["uuid"] == "target-profile"
    assert calls[1][2]["timeout"] == 120


def test_get_cdp_endpoint_restarts_profile_when_headless_mode_differs(
    monkeypatch,
) -> None:
    monkeypatch.setattr(facebook_runner, "OCTO_PROFILE_UUID", "target-profile")
    monkeypatch.setattr(facebook_runner, "OCTO_HEADLESS", True)
    monkeypatch.setattr(facebook_runner.time, "sleep", lambda _seconds: None)
    calls = []

    def fake_octo(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return [{
                "uuid": "target-profile",
                "headless": False,
                "ws_endpoint": "ws://127.0.0.1:1111/devtools/browser/visible",
            }]
        if path == "/api/profiles/stop":
            return {"ok": True}
        return {
            "ws_endpoint": "ws://127.0.0.1:2222/devtools/browser/headless",
            "connection_data": {"country": "Spain"},
        }

    monkeypatch.setattr(facebook_runner, "octo", fake_octo)

    ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()

    assert ws_endpoint.endswith("/headless")
    assert connection_data["country"] == "Spain"
    assert calls[1] == (
        "POST",
        "/api/profiles/stop",
        {"uuid": "target-profile"},
    )
    assert calls[2][2]["headless"] is True


def test_rewrite_cdp_endpoint_resolves_remote_host_for_chromium(monkeypatch) -> None:
    monkeypatch.setattr(
        facebook_runner.socket,
        "gethostbyname",
        lambda host: "192.0.2.10" if host == "host.docker.internal" else host,
    )

    endpoint = facebook_runner.rewrite_cdp_endpoint_host(
        "ws://127.0.0.1:59345/devtools/browser/browser-id",
        "host.docker.internal",
    )

    assert endpoint == "ws://192.0.2.10:59345/devtools/browser/browser-id"


def test_static_ad_permalink_is_resolved_by_opening_comments_read_only() -> None:
    page = StaticAdPage()
    ad = facebook_runner.Ad(
        advertiser="Saved advertiser",
        ad_type="link",
    )

    resolved = facebook_runner.resolve_facebook_post_url(
        page,
        ad,
        "feed-element",
    )

    assert resolved is True
    assert ad.facebook_page_url == "https://m.facebook.com/100"
    assert ad.facebook_post_url == (
        "https://m.facebook.com/story.php?story_fbid=200&id=100"
    )
    assert page.url == "https://m.facebook.com/"


def test_facebook_post_identity_rejects_external_urls() -> None:
    assert facebook_runner._facebook_post_identity_from_url(
        "https://m.facebook.com/100/posts/200"
    ) == ("100", "200")
    assert facebook_runner._facebook_post_identity_from_url(
        "https://example.com/100/posts/200"
    ) is None


def test_normalized_facebook_post_url_discards_tracking_query() -> None:
    assert facebook_runner._normalized_facebook_post_url(
        "https://m.facebook.com/story.php?id=100&story_fbid=200&refid=52"
    ) == "https://m.facebook.com/story.php?story_fbid=200&id=100"
    assert facebook_runner._normalized_facebook_post_url(
        "https://www.facebook.com/100/posts/200?mibextid=abc"
    ) == "https://m.facebook.com/100/posts/200"
