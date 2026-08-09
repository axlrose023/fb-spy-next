from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.facebook.runs import commands
from app.facebook.runs.adapters.persistence import FacebookRun


@pytest.mark.integration
async def test_completed_run_import_is_idempotent(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "completed-spain"
    run_dir.mkdir()
    ads_json = run_dir / "ads.json"
    ads_json.write_text("[]", encoding="utf-8")
    (run_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "profile_country": "Spain",
                "started_at": "2026-08-01T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "requested_minutes": 15,
                "finished_at": "2026-08-01T10:15:00Z",
            }
        ),
        encoding="utf-8",
    )

    first = await commands.import_run(ads_json)
    second = await commands.import_run(ads_json, title="ignored duplicate title")

    assert second.id == first.id
    assert first.status == "completed"
    assert first.title == "Spain - completed-spain"
    assert first.requested_minutes == 15
    assert first.started_at is not None
    assert first.finished_at is not None

    await session.execute(delete(FacebookRun).where(FacebookRun.id == first.id))
    await session.commit()


@pytest.mark.unit
def test_command_main_reports_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    ads_json = tmp_path / "ads.json"

    async def fake_import(path: Path, *, title: str = "") -> Any:
        assert (path, title) == (ads_json, "manual")
        return SimpleNamespace(
            id="run-id",
            total_ads=4,
            profile_country="Canada",
        )

    monkeypatch.setattr(commands, "import_run", fake_import)
    monkeypatch.setattr(
        sys,
        "argv",
        ["facebook-db-importer", "--ads-json", str(ads_json), "--title", "manual"],
    )

    assert commands.main() == 0
    assert "run_id=run-id ads=4 country=Canada" in capsys.readouterr().out


@pytest.mark.unit
def test_command_main_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    async def fail_import(_path: Path, *, title: str = "") -> Any:
        raise RuntimeError(f"cannot import {title}")

    monkeypatch.setattr(commands, "import_run", fail_import)
    monkeypatch.setattr(
        sys,
        "argv",
        ["facebook-db-importer", "--ads-json", str(tmp_path / "missing.json")],
    )

    assert commands.main() == 2
    assert "[backend-import] failed: RuntimeError" in capsys.readouterr().out
