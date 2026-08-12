from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from app.facebook.timing import utc_now


class _TeeStream:
    def __init__(self, *streams: TextIO) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()

    def isatty(self) -> bool:
        return any(
            getattr(stream, "isatty", lambda: False)() for stream in self.streams
        )


class DebugRecorder:
    def __init__(
        self,
        run_dir: Path,
        enabled: bool,
        *,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.enabled = enabled
        self.root = run_dir / "debug"
        self._clock = clock
        self._events: TextIO | None = None
        self._run_log: TextIO | None = None
        self._stdout: TextIO | None = None
        self._stderr: TextIO | None = None
        self._attached_pages: set[int] = set()
        self._event_counts: dict[str, int] = {}
        if not enabled:
            return
        for name in ("ads", "errors", "resolve", "viewports"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._events = (self.root / "events.jsonl").open(
            "a",
            encoding="utf-8",
            buffering=1,
        )
        self._run_log = (self.root / "run.log").open(
            "a",
            encoding="utf-8",
            buffering=1,
        )
        os.chmod(self.root / "events.jsonl", 0o600)
        os.chmod(self.root / "run.log", 0o600)
        self._stdout, self._stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeStream(sys.stdout, self._run_log)
        sys.stderr = _TeeStream(sys.stderr, self._run_log)
        self.event("debug_started")

    def event(self, kind: str, **data: Any) -> None:
        if not self.enabled or not self._events:
            return
        payload = self._compact({"at": self._clock(), "kind": kind, **data})
        try:
            self._events.write(
                json.dumps(payload, ensure_ascii=False, default=str) + "\n"
            )
        except Exception:
            pass

    @classmethod
    def _compact(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value if len(value) <= 1600 else value[:1600] + "...<truncated>"
        if isinstance(value, dict):
            return {str(key): cls._compact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._compact(item) for item in value[:100]]
        return value

    def limited_event(
        self,
        group: str,
        limit: int,
        kind: str,
        **data: Any,
    ) -> None:
        count = self._event_counts.get(group, 0) + 1
        self._event_counts[group] = count
        if count <= limit:
            self.event(kind, **data)
        elif count == limit + 1:
            self.event("events_suppressed", group=group, limit=limit)

    def attach_context(self, context: Any) -> None:
        if not self.enabled:
            return
        try:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            self.event("trace_started")
        except Exception as exc:
            self.event("trace_start_failed", error=repr(exc))
        for page in list(context.pages):
            self.attach_page(page)
        context.on("page", self.attach_page)

    def attach_page(self, page: Any) -> None:
        if not self.enabled or id(page) in self._attached_pages:
            return
        self._attached_pages.add(id(page))
        self.event("page_attached", url=self._page_url(page))
        page.on(
            "console",
            lambda message: self.limited_event(
                "console",
                120,
                "console",
                level=message.type,
                text=message.text,
                page_url=self._page_url(page),
            ),
        )
        page.on(
            "pageerror",
            lambda exc: self.event(
                "page_error",
                error=repr(exc),
                page_url=self._page_url(page),
            ),
        )
        page.on(
            "requestfailed",
            lambda request: self.limited_event(
                "network",
                160,
                "request_failed",
                method=request.method,
                url=request.url,
                failure=request.failure,
                page_url=self._page_url(page),
            ),
        )
        page.on(
            "response",
            lambda response: self._record_bad_response(page, response),
        )

    def _record_bad_response(self, page: Any, response: Any) -> None:
        try:
            if response.status >= 400:
                self.limited_event(
                    "network",
                    160,
                    "http_error",
                    status=response.status,
                    method=response.request.method,
                    url=response.url,
                    page_url=self._page_url(page),
                )
        except Exception:
            pass

    @staticmethod
    def _page_url(page: Any) -> str:
        try:
            url: str = page.url
            return url
        except Exception:
            return ""

    def screenshot(self, page: Any, relative: str, *, full_page: bool = False) -> None:
        if not self.enabled:
            return
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(path), full_page=full_page, timeout=8000)
        except Exception as exc:
            self.event(
                "debug_screenshot_failed",
                path=relative,
                error=repr(exc),
                page_url=self._page_url(page),
            )

    def write_json(self, relative: str, payload: Any) -> None:
        if not self.enabled:
            return
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
        except Exception as exc:
            self.event("debug_json_failed", path=relative, error=repr(exc))

    def write_text(self, relative: str, value: str) -> None:
        if not self.enabled:
            return
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(value, encoding="utf-8")
            os.chmod(path, 0o600)
        except Exception as exc:
            self.event("debug_text_failed", path=relative, error=repr(exc))

    def finish_context(self, context: Any) -> None:
        if not self.enabled:
            return
        try:
            self.event("debug_event_counts", counts=self._event_counts)
            context.tracing.stop(path=str(self.root / "trace.zip"))
            self.event("trace_stopped")
        except Exception as exc:
            self.event("trace_stop_failed", error=repr(exc))

    def close(self) -> None:
        if not self.enabled:
            return
        self.event("debug_finished")
        if self._stdout is not None:
            sys.stdout = self._stdout
        if self._stderr is not None:
            sys.stderr = self._stderr
        if self._events:
            self._events.close()
        if self._run_log:
            self._run_log.close()
