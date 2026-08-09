from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.facebook.collection.adapters.playwright import DebugRecorder
from app.services import facebook_runner

pytestmark = pytest.mark.unit


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_disabled_recorder_has_no_filesystem_or_stream_side_effects(
    tmp_path: Path,
) -> None:
    recorder = DebugRecorder(tmp_path, False)

    recorder.event("ignored")
    recorder.write_json("ads/ignored.json", {"ignored": True})
    recorder.write_text("ads/ignored.txt", "ignored")
    recorder.close()

    assert not (tmp_path / "debug").exists()


def test_recorder_writes_bounded_events_artifacts_and_run_output(
    tmp_path: Path,
) -> None:
    recorder = DebugRecorder(tmp_path, True, clock=lambda: "2026-08-09T12:00:00Z")
    try:
        print("captured runner output")
        recorder.event("payload", text="x" * 1700, values=list(range(120)))
        recorder.limited_event("console", 1, "console", text="first")
        recorder.limited_event("console", 1, "console", text="second")
        recorder.limited_event("console", 1, "console", text="third")
        recorder.write_json("ads/item.json", {"value": 7})
        recorder.write_text("ads/item.txt", "saved text")
    finally:
        recorder.close()

    events = _events(tmp_path / "debug" / "events.jsonl")
    assert [event["kind"] for event in events] == [
        "debug_started",
        "payload",
        "console",
        "events_suppressed",
        "debug_finished",
    ]
    assert events[1]["at"] == "2026-08-09T12:00:00Z"
    assert events[1]["text"].endswith("...<truncated>")
    assert len(events[1]["values"]) == 100
    assert events[3] == {
        "at": "2026-08-09T12:00:00Z",
        "kind": "events_suppressed",
        "group": "console",
        "limit": 1,
    }
    assert "captured runner output" in (tmp_path / "debug" / "run.log").read_text(
        encoding="utf-8"
    )
    assert json.loads(
        (tmp_path / "debug" / "ads" / "item.json").read_text(encoding="utf-8")
    ) == {"value": 7}
    assert (tmp_path / "debug" / "ads" / "item.txt").read_text(
        encoding="utf-8"
    ) == "saved text"


class FakeTracing:
    def __init__(self) -> None:
        self.started: dict[str, Any] | None = None
        self.stopped: dict[str, Any] | None = None

    def start(self, **options: Any) -> None:
        self.started = options

    def stop(self, **options: Any) -> None:
        self.stopped = options


class FakePage:
    url = "https://m.facebook.com/"

    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def screenshot(self, **_: Any) -> None:
        return None


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.pages = [page]
        self.tracing = FakeTracing()
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler


def test_recorder_attaches_each_page_once_and_records_trace_network_events(
    tmp_path: Path,
) -> None:
    page = FakePage()
    context = FakeContext(page)
    recorder = DebugRecorder(tmp_path, True, clock=lambda: "now")
    try:
        recorder.attach_context(context)
        recorder.attach_page(page)
        response = SimpleNamespace(
            status=503,
            url="https://example.test/failure",
            request=SimpleNamespace(method="GET"),
        )
        page.handlers["response"][0](response)
        recorder.finish_context(context)
    finally:
        recorder.close()

    assert context.tracing.started == {
        "screenshots": True,
        "snapshots": True,
        "sources": True,
    }
    assert context.tracing.stopped == {"path": str(tmp_path / "debug" / "trace.zip")}
    assert len(page.handlers["console"]) == 1
    assert len(page.handlers["response"]) == 1
    assert context.handlers["page"] == recorder.attach_page
    kinds = [event["kind"] for event in _events(tmp_path / "debug" / "events.jsonl")]
    assert kinds == [
        "debug_started",
        "trace_started",
        "page_attached",
        "http_error",
        "debug_event_counts",
        "trace_stopped",
        "debug_finished",
    ]


def test_runner_debug_recorder_alias_preserves_identity() -> None:
    assert facebook_runner.DebugRecorder is DebugRecorder
