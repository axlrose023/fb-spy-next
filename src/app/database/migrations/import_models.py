from app.settings import PathsConfig


def import_models(_config: PathsConfig) -> None:
    """Register the owning SQLAlchemy models for Alembic metadata."""
    from app.accounts.users.adapters.persistence import UserRecord
    from app.ad_library.ads.adapters.persistence import FacebookAd
    from app.facebook.runs.adapters.persistence import FacebookRun

    _ = (UserRecord, FacebookAd, FacebookRun)
