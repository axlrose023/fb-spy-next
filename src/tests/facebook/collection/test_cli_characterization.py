from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.facebook import commands as facebook_commands
from app.facebook.collection import commands as collection_commands
from app.facebook.collection.cli import artifacts, runtime, session
from app.services import facebook_runner

pytestmark = pytest.mark.unit


def test_collection_command_owns_public_and_legacy_entrypoints() -> None:
    collect = next(
        command for command in facebook_commands.COMMANDS if command.name == "collect"
    )
    assert collect.module == "app.facebook.collection.commands"
    assert facebook_runner.main is collection_commands.main
    assert facebook_runner._write_ads is artifacts.write_ads
    assert facebook_runner._write_json_atomic is artifacts.write_json_atomic
    assert facebook_runner._write_text_atomic is artifacts.write_text_atomic
    assert facebook_runner._write_run_meta is artifacts.write_run_meta
    assert (
        facebook_runner._fast_exit_after_browser_operation_timeout
        is artifacts.fast_exit_after_browser_operation_timeout
    )
    assert (
        facebook_runner._octo_start_failure_reason
        is artifacts.octo_start_failure_reason
    )
    assert (
        facebook_runner._write_octo_start_failure is artifacts.write_octo_start_failure
    )


class FakePage:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeContext:
    def __init__(self) -> None:
        self.pages = [FakePage("https://m.facebook.com/")]
        self.created_page = FakePage("about:blank")

    def new_page(self) -> FakePage:
        self.pages.append(self.created_page)
        return self.created_page


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.contexts = [context]


class FakeChromium:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.endpoints: list[str] = []

    def connect_over_cdp(self, endpoint: str) -> FakeBrowser:
        self.endpoints.append(endpoint)
        return FakeBrowser(self.context)


class FakePlaywright:
    def __init__(self, context: FakeContext) -> None:
        self.chromium = FakeChromium(context)


class FakePlaywrightManager:
    def __init__(self, context: FakeContext) -> None:
        self.playwright = FakePlaywright(context)

    def __enter__(self) -> FakePlaywright:
        return self.playwright

    def __exit__(self, *_args: object) -> None:
        pass


class FakeDebugRecorder:
    instances: list[FakeDebugRecorder] = []

    def __init__(self, run_dir: Path, enabled: bool, **_kwargs: object) -> None:
        self.run_dir = run_dir
        self.enabled = enabled
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.attached = 0
        self.finished = 0
        self.closed = False
        self.instances.append(self)

    @staticmethod
    def _page_url(page: FakePage) -> str:
        return page.url

    def event(self, name: str, **fields: Any) -> None:
        self.events.append((name, fields))

    def attach_context(self, _context: FakeContext) -> None:
        self.attached += 1

    def finish_context(self, _context: FakeContext) -> None:
        self.finished += 1

    def screenshot(self, *_args: object, **_kwargs: object) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_collection_cli_maps_passive_topic_run_without_active_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = FakeContext()
    manager = FakePlaywrightManager(context)
    collect_call: dict[str, Any] = {}
    neutralized: list[tuple[FakePage, FakeContext]] = []
    FakeDebugRecorder.instances.clear()
    monkeypatch.setattr(collection_commands.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        facebook_runner,
        "get_cdp_endpoint",
        lambda: ("ws://127.0.0.1:9999/devtools/browser/id", {"country": "Canada"}),
    )
    monkeypatch.setattr(
        facebook_runner,
        "rewrite_cdp_endpoint_host",
        lambda endpoint, _host: endpoint,
    )
    monkeypatch.setattr(
        session,
        "sync_playwright",
        lambda: manager,
    )
    monkeypatch.setattr(runtime, "DebugRecorder", FakeDebugRecorder)
    monkeypatch.setattr(
        session,
        "neutralize_profile_pages",
        lambda page, ctx: neutralized.append((page, ctx)),
    )
    monkeypatch.setattr(
        runtime,
        "fast_exit_after_browser_operation_timeout",
        lambda _run_dir: None,
    )

    def collect(
        page: FakePage,
        ctx: FakeContext,
        run_dir: Path,
        **kwargs: Any,
    ) -> dict[str, facebook_runner.Ad]:
        collect_call.update(page=page, context=ctx, run_dir=run_dir, kwargs=kwargs)
        return {
            "one": facebook_runner.Ad(
                advertiser="Relevant",
                ad_type="link",
                country="Canada",
            )
        }

    monkeypatch.setattr(runtime, "collect_feed", collect)
    run_dir = tmp_path / "exact-run"

    result = facebook_runner.main(
        [
            "--run-dir",
            str(run_dir),
            "--octo-profile-uuid",
            "profile-1",
            "--topic",
            "health news",
            "--passive-collect",
            "--debug",
        ]
    )

    kwargs = collect_call["kwargs"]
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    ads = json.loads((run_dir / "ads.json").read_text(encoding="utf-8"))
    recorder = FakeDebugRecorder.instances[-1]
    assert result == 0
    assert collect_call["page"] is context.created_page
    assert kwargs["feed_url"] == ("https://m.facebook.com/search/top/?q=health+news")
    assert kwargs["do_resolve"] is False
    assert kwargs["record_videos"] is False
    assert kwargs["resolve_post_urls"] is False
    assert kwargs["interest_safe_mode"] is True
    assert neutralized == [(context.created_page, context)]
    assert meta["octo_profile_uuid"] == "profile-1"
    assert meta["profile_country"] == "Canada"
    assert ads[0]["advertiser"] == "Relevant"
    assert recorder.attached == 1
    assert recorder.finished == 1
    assert recorder.closed is True


def test_collection_cli_writes_octo_failure_and_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeDebugRecorder.instances.clear()
    monkeypatch.setattr(collection_commands.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(runtime, "DebugRecorder", FakeDebugRecorder)
    monkeypatch.setattr(
        facebook_runner,
        "get_cdp_endpoint",
        lambda: (_ for _ in ()).throw(
            facebook_runner.OctoApiError('HTTP 400 {"code":"profiles.proxy_error"}')
        ),
    )
    run_dir = tmp_path / "failed-run"

    result = facebook_runner.main(
        [
            "--run-dir",
            str(run_dir),
            "--octo-profile-uuid",
            "profile-2",
            "--minutes",
            "15",
        ]
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert result == 2
    assert summary["stop_reason"] == "octo_proxy_error"
    assert summary["requested_minutes"] == 15
    assert FakeDebugRecorder.instances[-1].closed is True
