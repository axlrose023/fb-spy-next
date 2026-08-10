import json
from configparser import ConfigParser
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import anyio
import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.users.adapters.persistence import UserRecord as User
from app.ad_library.ads.adapters.persistence import FacebookAd
from app.ad_library.ads.ingestion.language import language_from_raw_ad
from app.ad_library.media import MEDIA_SPECS
from app.ad_library.media.configuration import configured_storage
from app.ad_library.media.paths.object_keys import S3_REFERENCE_PREFIX
from app.database.engine import SessionFactory
from app.database.uow import UnitOfWork
from app.facebook.enrichment import archive_filename, archive_landing_http
from app.facebook.relevance import configured_relevance_service
from app.facebook.runs.adapters import FacebookAdsImporter
from app.facebook.runs.adapters.persistence import FacebookRun
from app.ioc import get_async_container
from app.settings import get_config

app = typer.Typer()


alembic_ini_path = Path(__file__).parent.parent.parent / "alembic.ini"


def get_alembic_config() -> Config:
    if not alembic_ini_path.exists():
        raise FileNotFoundError("alembic.ini not found")
    return Config("alembic.ini")


@app.command("migration")
def migration(name: Annotated[str | None, typer.Option(prompt=True)] = None) -> None:
    """Generate a new Alembic migration."""
    alembic_cfg = get_alembic_config()
    command.revision(alembic_cfg, message=name, autogenerate=True)
    typer.echo(
        typer.style(
            f"New migration '{name}' created successfully.",
            fg=typer.colors.GREEN,
        ),
    )


@app.command("migrations")
def migrations() -> None:
    """list migration files."""
    if not alembic_ini_path.exists():
        raise FileNotFoundError("alembic.ini not found")
    config = ConfigParser()
    config.read(alembic_ini_path)
    migrations_path = config.get("alembic", "script_location")
    typer.echo(f"Migration files are located in: {migrations_path}")
    migration_dir = Path(migrations_path) / "versions"
    for file in migration_dir.glob("*.py"):
        typer.echo(f"- {file}")


@app.command("upgrade")
def upgrade(revision: str = "head") -> None:
    """Upgrade the database to a specific revision."""
    alembic_cfg = get_alembic_config()
    command.upgrade(alembic_cfg, revision)
    typer.echo(
        typer.style(
            f"Database upgraded to revision '{revision}' successfully.",
            fg=typer.colors.GREEN,
        ),
    )


@app.command("downgrade")
def downgrade(revision: str = "-1") -> None:
    """Downgrade the database to a specific revision."""
    alembic_cfg = get_alembic_config()
    command.downgrade(alembic_cfg, revision)
    typer.echo(
        typer.style(
            f"Database downgraded to revision '{revision}' successfully.",
            fg=typer.colors.GREEN,
        ),
    )


@app.command("create_user")
def create_user(
    username: Annotated[str, typer.Option(prompt=True)] = None,
    password: Annotated[str, typer.Option(prompt=True, hide_input=True)] = None,
) -> None:
    """Create a new user."""

    async def _create_user():
        from passlib.context import CryptContext

        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        container = get_async_container()
        async with container() as request_container:
            uow = await request_container.get(UnitOfWork)
            hashed_password = pwd_context.hash(password)
            user = User(
                username=username,
                password=hashed_password,
                is_active=True,
            )
            await uow.users.create(user)
            await uow.commit()
            typer.echo(f"User '{username}' created successfully.")

    anyio.run(_create_user)


@app.command("filter-facebook-ads")
def filter_facebook_ads(
    ads_json_path: Annotated[
        Path, typer.Argument(help="Path to a Facebook runner ads.json")
    ],
    run_id: Annotated[
        str | None, typer.Option(help="Existing run id to replace in DB")
    ] = None,
) -> None:
    """Filter an existing Facebook ads.json through Gemini relevance."""

    async def _filter_ads() -> None:
        config = get_config()
        relevance_filter = configured_relevance_service(config)
        if not relevance_filter.enabled:
            raise typer.BadParameter(
                "Relevance filter is disabled. Set APP__FACEBOOK__RELEVANCE_FILTER_ENABLED=true "
                "and APP__GEMINI__API_KEY."
            )

        path = ads_json_path.expanduser().resolve()
        raw_ads = json.loads(path.read_text(encoding="utf-8"))
        accepted, rejected = await relevance_filter.filter_raw_ads(raw_ads, path.parent)
        FacebookAdsImporter._write_filter_outputs(
            path, accepted, rejected, len(raw_ads)
        )

        if run_id:
            async with SessionFactory() as session:
                async with UnitOfWork(session) as uow:
                    run = await uow.facebook_runs.get_by_id(UUID(run_id))
                    if not run:
                        raise typer.BadParameter(f"Run not found: {run_id}")
                    importer = FacebookAdsImporter(config)
                    await importer.import_ads_json(
                        uow, run, path, apply_relevance=False
                    )
                    await uow.commit()

        typer.echo(
            typer.style(
                f"Filtered {len(raw_ads)} ads: accepted={len(accepted)} rejected={len(rejected)}",
                fg=typer.colors.GREEN,
            ),
        )

    anyio.run(_filter_ads)


@app.command("archive-facebook-landings")
def archive_facebook_landings(
    run_id: Annotated[
        str | None, typer.Option(help="Only archive ads from this run")
    ] = None,
    ad_id: Annotated[str | None, typer.Option(help="Only archive one ad id")] = None,
    limit: Annotated[int, typer.Option(help="Maximum ads to process; 0 means all")] = 0,
    overwrite: Annotated[
        bool, typer.Option(help="Rebuild archives that already exist")
    ] = False,
    timeout_seconds: Annotated[
        float, typer.Option(help="HTTP timeout per request")
    ] = 20.0,
    max_resources: Annotated[
        int, typer.Option(help="Maximum linked resources per archive")
    ] = 120,
) -> None:
    """Build landing-page zip archives for existing ads with landing_full."""

    async def _archive() -> None:
        config = get_config()
        importer = FacebookAdsImporter(config)
        async with SessionFactory() as session:
            verified_run_ids = await _verified_relevant_run_ids(session)
            stmt = (
                select(FacebookAd, FacebookRun)
                .join(FacebookRun, FacebookAd.run_id == FacebookRun.id)
                .where(FacebookAd.landing_full.is_not(None))
                .where(FacebookAd.run_id.in_(verified_run_ids))
                .order_by(
                    FacebookAd.captured_at.desc().nullslast(),
                    FacebookAd.created_at.desc(),
                )
            )
            if not overwrite:
                stmt = stmt.where(FacebookAd.landing_archive_path.is_(None))
            if run_id:
                stmt = stmt.where(FacebookAd.run_id == UUID(run_id))
            if ad_id:
                stmt = stmt.where(FacebookAd.id == UUID(ad_id))
            if limit > 0:
                stmt = stmt.limit(limit)

            rows = (await session.execute(stmt)).all()
            if not rows:
                typer.echo("No ads need landing archives.")
                return

            ok = failed = 0
            for index, (ad, run) in enumerate(rows, start=1):
                run_dir = _resolve_run_dir(config, run)
                landing_full = ad.landing_full
                if not landing_full:
                    continue
                archive_path = (
                    run_dir
                    / "landing_archives"
                    / archive_filename(
                        ad.source_index or index, ad.displayed_domain, landing_full
                    )
                )
                typer.echo(
                    f"[{index}/{len(rows)}] {ad.displayed_domain or ad.advertiser} -> {archive_path.name}"
                )
                result = await anyio.to_thread.run_sync(
                    lambda landing_url=landing_full, target_path=archive_path: (
                        archive_landing_http(
                            landing_url,
                            target_path,
                            timeout_seconds=timeout_seconds,
                            max_resources=max_resources,
                        )
                    )
                )
                if result.ok:
                    ad.landing_archive_path = importer._runner_media_path(
                        run_dir,
                        str(archive_path),
                    )
                    ad.updated_at = datetime.now(UTC)
                    _update_runner_json_archive(
                        run_dir,
                        ad,
                        archive_path.relative_to(run_dir).as_posix(),
                    )
                    await importer.media_storage.upload_ads(
                        [ad],
                        relevance_verified=True,
                    )
                    ok += 1
                    await session.flush()
                else:
                    failed += 1
                    typer.echo(
                        typer.style(
                            f"  failed: {'; '.join(result.errors[-3:]) or 'unknown error'}",
                            fg=typer.colors.RED,
                        )
                    )
            await session.commit()
            typer.echo(
                typer.style(
                    f"Landing archives built: ok={ok} failed={failed}",
                    fg=typer.colors.GREEN if failed == 0 else typer.colors.YELLOW,
                )
            )

    anyio.run(_archive)


@app.command("sync-facebook-media")
def sync_facebook_media(
    run_id: Annotated[str | None, typer.Option(help="Only sync one run id")] = None,
    ad_id: Annotated[str | None, typer.Option(help="Only sync one ad id")] = None,
    limit: Annotated[int, typer.Option(help="Maximum ads to sync; 0 means all")] = 0,
    batch_size: Annotated[int, typer.Option(help="Ads committed per batch")] = 50,
) -> None:
    """Upload existing Facebook media to configured S3 storage."""

    async def _sync() -> None:
        config = get_config()
        if config.media.backend != "s3":
            raise typer.BadParameter("Set APP__MEDIA__BACKEND=s3 before syncing media.")
        if not 1 <= batch_size <= 500:
            raise typer.BadParameter("batch-size must be between 1 and 500")

        storage = configured_storage(config)
        media_columns = [
            getattr(FacebookAd, spec.model_attribute) for spec in MEDIA_SPECS.values()
        ]
        needs_upload = or_(
            *(
                and_(
                    column.is_not(None),
                    column != "",
                    column.not_like(f"{S3_REFERENCE_PREFIX}%"),
                )
                for column in media_columns
            )
        )
        synced_ads = uploaded_objects = 0
        async with SessionFactory() as session:
            verified_run_ids = await _verified_relevant_run_ids(session)
            while limit <= 0 or synced_ads < limit:
                current_limit = batch_size
                if limit > 0:
                    current_limit = min(current_limit, limit - synced_ads)
                stmt = (
                    select(FacebookAd)
                    .where(needs_upload)
                    .where(FacebookAd.run_id.in_(verified_run_ids))
                    .order_by(FacebookAd.created_at, FacebookAd.id)
                    .limit(current_limit)
                )
                if run_id:
                    stmt = stmt.where(FacebookAd.run_id == UUID(run_id))
                if ad_id:
                    stmt = stmt.where(FacebookAd.id == UUID(ad_id))
                ads = list((await session.scalars(stmt)).all())
                if not ads:
                    break
                uploaded_objects += await storage.upload_ads(
                    ads,
                    relevance_verified=True,
                )
                await session.commit()
                synced_ads += len(ads)
                typer.echo(
                    f"Synced ads={synced_ads} objects={uploaded_objects}",
                )
        typer.echo(
            typer.style(
                f"S3 media sync complete: ads={synced_ads} objects={uploaded_objects}",
                fg=typer.colors.GREEN,
            )
        )

    anyio.run(_sync)


@app.command("backfill-facebook-ad-languages")
def backfill_facebook_ad_languages(
    dry_run: Annotated[
        bool,
        typer.Option(help="Report changes without updating the database"),
    ] = False,
) -> None:
    """Fill missing ad languages from saved classified runner JSON."""

    async def _backfill() -> None:
        async with SessionFactory() as session:
            rows = (
                await session.execute(
                    select(FacebookAd, FacebookRun)
                    .join(FacebookRun, FacebookAd.run_id == FacebookRun.id)
                    .where(FacebookAd.language.is_(None))
                    .order_by(FacebookRun.id, FacebookAd.source_index)
                )
            ).all()
            cache: dict[str, list[dict]] = {}
            updated = missing_file = unmatched = unknown = 0
            for ad, run in rows:
                path_value = run.ads_json_path or ""
                if path_value not in cache:
                    cache[path_value] = _read_ads_json(Path(path_value))
                raw_ads = cache[path_value]
                if not raw_ads:
                    missing_file += 1
                    continue
                raw = _match_raw_ad(ad, raw_ads)
                if raw is None:
                    unmatched += 1
                    continue
                language = language_from_raw_ad(raw)
                if not language:
                    unknown += 1
                    continue
                ad.language = language
                updated += 1
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
            typer.echo(
                "Facebook ad language backfill: "
                f"updated={updated} missing_file={missing_file} "
                f"unmatched={unmatched} unknown={unknown} dry_run={dry_run}"
            )

    anyio.run(_backfill)


def _read_ads_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _match_raw_ad(ad: FacebookAd, raw_ads: list[dict]) -> dict | None:
    if ad.fb_ad_id:
        for raw in raw_ads:
            if str(raw.get("fb_ad_id") or "").strip() == ad.fb_ad_id:
                return raw
    if ad.source_key:
        for index, raw in enumerate(raw_ads, start=1):
            if FacebookAdsImporter._source_key(raw, index) == ad.source_key:
                return raw
    return None


async def _verified_relevant_run_ids(session: AsyncSession) -> set[UUID]:
    rows = (
        await session.execute(
            select(FacebookRun, func.count(FacebookAd.id))
            .join(FacebookAd, FacebookAd.run_id == FacebookRun.id)
            .group_by(FacebookRun.id)
        )
    ).all()
    verified: set[UUID] = set()
    for run, ad_count in rows:
        try:
            raw_ads = json.loads(
                Path(run.ads_json_path or "").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(raw_ads, list)
            and len(raw_ads) == ad_count
            and FacebookAdsImporter.raw_ads_explicitly_relevant(raw_ads)
        ):
            verified.add(run.id)
    return verified


def _resolve_run_dir(config, run: FacebookRun) -> Path:
    candidates: list[Path] = []
    if run.runner_run_dir:
        raw = Path(run.runner_run_dir).expanduser()
        candidates.extend([raw, Path.cwd() / raw])
    if run.ads_json_path:
        raw_ads = Path(run.ads_json_path).expanduser()
        candidates.extend([raw_ads.parent, Path.cwd() / raw_ads.parent])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    fallback = config.facebook.data_dir / "manual_landing_archives" / str(run.id)
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback.resolve()


def _update_runner_json_archive(
    run_dir: Path, ad: FacebookAd, archive_relative: str
) -> None:
    for name in ("ads.json", "ads.unfiltered.json", "ads.partial.json"):
        path = run_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        changed = False
        for raw in data:
            if not isinstance(raw, dict):
                continue
            same_fb_id = ad.fb_ad_id and raw.get("fb_ad_id") == ad.fb_ad_id
            same_landing = raw.get("landing_full") == ad.landing_full
            if same_fb_id or same_landing:
                raw["landing_archive"] = archive_relative
                changed = True
        if changed:
            FacebookAdsImporter._write_json_atomic(path, data)
