"""Import one already-classified orchestrator run into the application DB."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.api.modules.runs.models import FacebookRun
from app.database.engine import SessionFactory
from app.database.uow import UnitOfWork
from app.services.facebook.importer import FacebookAdsImporter
from app.settings import get_config


async def import_run(ads_json_path: Path, *, title: str = "") -> FacebookRun:
    path = ads_json_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    run_dir = path.parent
    meta = _load_json(run_dir / "run_meta.json", default={})
    summary = _load_json(run_dir / "summary.json", default={})

    async with SessionFactory() as session:
        existing = await session.scalar(
            select(FacebookRun)
            .where(FacebookRun.runner_run_dir == str(run_dir))
            .limit(1)
        )
        if existing is not None:
            return existing

        run = FacebookRun(
            status="completed",
            title=title or _default_title(meta, run_dir),
            requested_minutes=float(summary.get("requested_minutes") or 0.0),
            runner_run_dir=str(run_dir),
            ads_json_path=str(path),
            log_path=str(run_dir / "runner.log"),
            return_code=0,
            started_at=_parse_datetime(meta.get("started_at")),
            finished_at=(
                _parse_datetime(summary.get("finished_at")) or datetime.now(UTC)
            ),
        )
        async with UnitOfWork(session) as uow:
            await uow.facebook_runs.create(run)
            importer = FacebookAdsImporter(get_config())
            await importer.import_ads_json(
                uow,
                run,
                path,
                apply_relevance=False,
            )
            await uow.commit()
            await uow.refresh(run)
        return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ads-json", type=Path, required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args()
    try:
        run = asyncio.run(import_run(args.ads_json, title=args.title))
    except Exception as exc:
        print(f"[backend-import] failed: {exc!r}", flush=True)
        return 2
    print(
        f"[backend-import] run_id={run.id} ads={run.total_ads} "
        f"country={run.profile_country or '-'}",
        flush=True,
    )
    return 0


def _default_title(meta: dict[str, Any], run_dir: Path) -> str:
    country = str(meta.get("profile_country") or "Facebook").strip()
    return f"{country} - {run_dir.name}"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _load_json(path: Path, *, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
