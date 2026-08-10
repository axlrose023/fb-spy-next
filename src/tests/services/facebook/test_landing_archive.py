import json
import zipfile

import httpx

from app.facebook.enrichment import (
    LandingArchiveResult,
    archive_landing_http,
    archive_landing_page_from_browser,
    save_landing_screenshot_from_browser,
)
from app.facebook.enrichment.media.archive import http_capture
from app.facebook.enrichment.media.archive import service as archive_service


def test_archive_landing_skips_error_documents_and_keeps_original_refs(
    monkeypatch,
    tmp_path,
) -> None:
    base_url = "https://landing.example/page"
    requests: list[tuple[str, dict[str, str] | None]] = []

    routes = {
        base_url: (
            200,
            "text/html",
            b"""
            <html><head>
              <link rel="stylesheet" href="/ok.css">
              <link rel="stylesheet" href="/missing.css">
              <script src="/broken.js"></script>
            </head><body>
              <img src="/deny.png">
              <img src="/logo.png">
              <iframe src="/frame.html"></iframe>
            </body></html>
            """,
        ),
        "https://landing.example/ok.css": (
            200,
            "text/css",
            b".hero{background:url('/bg.png')}",
        ),
        "https://landing.example/bg.png": (200, "image/png", b"\x89PNG\r\n\x1a\nbg"),
        "https://landing.example/logo.png": (
            200,
            "image/png",
            b"\x89PNG\r\n\x1a\nlogo",
        ),
        "https://landing.example/frame.html": (
            200,
            "text/html",
            b"<html><body>frame</body></html>",
        ),
        "https://landing.example/missing.css": (
            404,
            "text/html",
            b"<html><title>404 Not Found</title></html>",
        ),
        "https://landing.example/broken.js": (
            200,
            "text/html",
            b"<html><title>404 Not Found</title></html>",
        ),
        "https://landing.example/deny.png": (
            200,
            "application/xml",
            b"<?xml version='1.0'?><Error><Code>AccessDenied</Code></Error>",
        ),
    }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.cookies = httpx.Cookies()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None):
            requests.append((url, headers))
            status, content_type, body = routes[url]
            return httpx.Response(
                status,
                content=body,
                headers={"content-type": content_type},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(http_capture.httpx, "Client", FakeClient)

    archive_path = tmp_path / "landing.zip"
    result = archive_landing_http(base_url, archive_path)

    assert result.ok
    assert len(result.resources) == 4
    assert all(resource.status_code == 200 for resource in result.resources)
    assert any("missing.css: skipped status 404" in error for error in result.errors)
    assert any("broken.js: skipped error document" in error for error in result.errors)
    assert any("deny.png: skipped error document" in error for error in result.errors)

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert any(name.endswith("_ok.css") for name in names)
        assert any(name.endswith("_logo.png") for name in names)
        assert any(name.endswith("_frame.html") for name in names)
        assert not any(name.endswith("_missing.css") for name in names)
        assert not any(name.endswith("_broken.js") for name in names)
        assert not any(name.endswith("_deny.png") for name in names)

        index = archive.read("index.html").decode()
        assert "assets/" in index
        assert "/missing.css" in index
        assert "/broken.js" in index
        assert "/deny.png" in index
        rewritten_css = archive.read(
            next(name for name in names if name.endswith("_ok.css"))
        ).decode()
        assert "/bg.png" not in rewritten_css
        assert "_bg.png" in rewritten_css

        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["resources"]) == 4
        assert len(manifest["errors"]) == 3

    asset_requests = [request for request in requests if request[0] != base_url]
    assert asset_requests
    assert all(
        headers and headers.get("Referer") == base_url for _, headers in asset_requests
    )
    assert all(
        headers and headers.get("Accept") == "*/*" for _, headers in asset_requests
    )


def test_archive_landing_page_from_browser_uses_browser_artifacts(
    monkeypatch,
    tmp_path,
) -> None:
    def fail_http(*args, **kwargs):
        raise AssertionError("browser archive should not fetch landing over http")

    monkeypatch.setattr(archive_service, "archive_landing_http", fail_http)

    page = FakeBrowserPage()
    relative = archive_landing_page_from_browser(
        page,
        tmp_path,
        source_index=7,
        domain="cloak.example",
        url="https://cloak.example/click?fbclid=123",
    )

    assert relative
    archive_path = tmp_path / relative
    assert archive_path.exists()
    assert page.load_states == ["domcontentloaded", "load"]
    assert page.waited_for_timeout
    assert page.screenshot_calls == [(None, True, 15000)]

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert "index.html" in names
        assert "index.original.html" in names
        assert "browser/dom.html" in names
        assert "browser/page.mhtml" in names
        assert "browser/screenshot_loaded.png" in names

        index = archive.read("index.html").decode()
        assert '<base href="https://cloak.example/live">' not in index
        assert 'src="browser/screenshot_loaded.png"' in index
        assert 'href="browser/page.mhtml"' in index
        assert "https://cloak.example/live" in index

        captured_dom = archive.read("browser/dom.html").decode()
        assert "browser-rendered cloak page" in captured_dom

        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == 2
        assert manifest["capture_source"] == "browser"
        assert manifest["offline_entrypoint"] == "index.html"
        assert manifest["source_url"] == "https://cloak.example/click?fbclid=123"
        assert manifest["final_url"] == "https://cloak.example/live"
        assert manifest["resources"] == []
        assert any(
            item["path"] == "browser/page.mhtml" for item in manifest["artifacts"]
        )


def test_browser_archive_reuses_previously_captured_full_page_screenshot(
    monkeypatch,
    tmp_path,
) -> None:
    def fail_http(*args, **kwargs):
        raise AssertionError("valid browser artifacts should not use HTTP fallback")

    monkeypatch.setattr(archive_service, "archive_landing_http", fail_http)
    fallback_path = tmp_path / "landing_screens" / "loaded.png"
    fallback_path.parent.mkdir()
    fallback_path.write_bytes(FakeBrowserPage.PNG)

    page = ScreenshotTimeoutBrowserPage()
    relative = archive_landing_page_from_browser(
        page,
        tmp_path,
        source_index=8,
        domain="slow-fonts.example",
        url="https://slow-fonts.example/click",
        fallback_screenshot_path=fallback_path,
    )

    assert relative
    with zipfile.ZipFile(tmp_path / relative) as archive:
        assert archive.read("browser/screenshot_loaded.png") == FakeBrowserPage.PNG
        assert b"browser/screenshot_loaded.png" in archive.read("index.html")
        manifest = json.loads(archive.read("manifest.json"))
        assert not any(error.startswith("screenshot:") for error in manifest["errors"])
    assert page.screenshot_calls == []


def test_landing_archive_result_rejects_non_zip_file(tmp_path) -> None:
    archive_path = tmp_path / "broken.zip"
    archive_path.write_bytes(b"not a zip")

    result = LandingArchiveResult(
        archive_path=archive_path,
        source_url="https://landing.example",
    )

    assert result.ok is False


def test_save_landing_screenshot_from_browser_writes_loaded_screenshot(
    tmp_path,
) -> None:
    page = FakeBrowserPage()

    relative = save_landing_screenshot_from_browser(
        page,
        tmp_path,
        source_index=3,
        domain="cloak.example",
        url="https://cloak.example/click?fbclid=456",
    )

    assert relative
    screenshot_path = tmp_path / relative
    assert screenshot_path.exists()
    assert screenshot_path.read_bytes() == FakeBrowserPage.PNG
    assert relative.startswith("landing_screens/")
    assert relative.endswith("_loaded.png")
    assert page.screenshot_calls == [(str(screenshot_path), True, 15000)]


class FakeBrowserPage:
    PNG = b"\x89PNG\r\n\x1a\nloaded"

    def __init__(self) -> None:
        self.url = "https://cloak.example/live"
        self.context = FakeBrowserContext()
        self.load_states: list[str] = []
        self.waited_for_function = False
        self.waited_for_timeout = False
        self.screenshot_calls: list[tuple[str | None, bool, int]] = []

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.load_states.append(state)

    def wait_for_function(self, expression: str, timeout: int) -> None:
        self.waited_for_function = True

    def wait_for_timeout(self, timeout: int) -> None:
        self.waited_for_timeout = True

    def evaluate(self, expression: str) -> str:
        if "navigator.userAgent" in expression:
            return "Octo Chrome"
        return ""

    def title(self) -> str:
        return "Cloaked landing"

    def content(self) -> str:
        return "<html><head></head><body>browser-rendered cloak page</body></html>"

    def screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
        timeout: int = 0,
    ) -> bytes:
        self.screenshot_calls.append((path, full_page, timeout))
        if path:
            from pathlib import Path

            Path(path).write_bytes(self.PNG)
        return self.PNG


class ScreenshotTimeoutBrowserPage(FakeBrowserPage):
    def screenshot(
        self,
        path: str | None = None,
        full_page: bool = False,
        timeout: int = 0,
    ) -> bytes:
        self.screenshot_calls.append((path, full_page, timeout))
        raise TimeoutError("fonts did not finish loading")


class FakeBrowserContext:
    def new_cdp_session(self, page):
        return FakeCdpSession()


class FakeCdpSession:
    def send(self, method: str, payload: dict):
        assert method == "Page.captureSnapshot"
        assert payload == {"format": "mhtml"}
        return {"data": "MIME-Version: 1.0\n\nbrowser mhtml"}
