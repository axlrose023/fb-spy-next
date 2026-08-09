from pathlib import Path
from types import SimpleNamespace

import pytest

from app.facebook.relevance.adapters import isolated_browser, isolation, landing_capture
from app.facebook.relevance.files import load_ads

pytestmark = pytest.mark.unit


class _Route:
    def __init__(self, url: str, *, resource_type: str = "document") -> None:
        self.action = ""
        self.request = SimpleNamespace(
            url=url,
            resource_type=resource_type,
            frame=SimpleNamespace(url=url),
        )

    def abort(self) -> None:
        self.action = "abort"

    def continue_(self) -> None:
        self.action = "continue"


def test_network_guard_blocks_meta_and_private_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isolation, "host_is_public", lambda host: host == "public.example")
    guard = isolation.NetworkGuard()
    meta = _Route("https://www.facebook.com/tracking")
    private = _Route("http://127.0.0.1/admin")
    public = _Route("https://public.example/page")

    guard.handle(meta)
    guard.handle(private)
    guard.handle(public)

    assert (meta.action, private.action, public.action) == (
        "abort",
        "abort",
        "continue",
    )
    assert guard.meta_requests_blocked == 1
    assert guard.private_requests_blocked == 1


def test_prepare_candidates_marks_unresolvable_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        isolated_browser,
        "host_is_public",
        lambda host: host == "offer.example",
    )
    rows = [
        {"relevance_gate": "hold", "cta_href": "https://offer.example/start"},
        {"relevance_gate": "hold"},
        {"relevance_gate": "allow"},
    ]

    candidates = isolated_browser._prepare_candidates(rows)

    assert candidates == [(0, "passive_cta_href", "https://offer.example/start")]
    assert rows[1]["isolated_resolution"]["active_profile_actions_started"] is False


def test_isolated_runner_without_candidates_never_starts_browser(tmp_path: Path) -> None:
    source = tmp_path / "ads.prefilter.json"
    source.write_text('[{"relevance_gate":"deny"}]', encoding="utf-8")
    args = SimpleNamespace(run_dir=tmp_path, source=None, output=None)

    assert isolated_browser.run_isolated_browser(args) == 0
    assert load_ads(tmp_path / "ads.isolated.json") == [{"relevance_gate": "deny"}]


def test_reuse_resolution_copies_only_evidence_artifacts() -> None:
    target: dict = {}
    cached = {
        "row": {
            "landing_full": "https://offer.example/start",
            "landing_screenshot": "screens/landing.png",
            "secret": "must-not-copy",
            "isolated_resolution": {"status": "completed", "source": "passive_cta_href"},
        }
    }

    landing_capture.reuse_resolution(target, cached, source_row_index=4)

    assert target["landing_full"] == "https://offer.example/start"
    assert target["isolated_resolution"]["source_row_index"] == 4
    assert "secret" not in target
