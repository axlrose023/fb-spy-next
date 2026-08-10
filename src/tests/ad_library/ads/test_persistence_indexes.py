import pytest
from sqlalchemy import Index
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect

from app.ad_library.ads.adapters.persistence import FacebookAd
from app.ad_library.ads.adapters.persistence.indexes import GEO_FACEBOOK_ID_INDEX

pytestmark = pytest.mark.contract


def _predicate(index: Index, dialect: Dialect) -> str:
    where = index.dialect_options[dialect.name]["where"]
    return str(
        where.compile(
            dialect=dialect,
            compile_kwargs={"literal_binds": True},
        )
    )


def test_geo_facebook_id_index_matches_migration_contract() -> None:
    index = next(
        item
        for item in FacebookAd.__table__.indexes
        if item.name == GEO_FACEBOOK_ID_INDEX
    )

    assert index.unique is True
    assert [str(expression) for expression in index.expressions] == [
        "lower(facebook_ads.country)",
        "facebook_ads.fb_ad_id",
    ]
    expected = (
        "facebook_ads.country IS NOT NULL "
        "AND facebook_ads.country != '' "
        "AND facebook_ads.fb_ad_id IS NOT NULL "
        "AND facebook_ads.fb_ad_id != ''"
    )
    assert _predicate(index, postgresql.dialect()) == expected
    assert _predicate(index, sqlite.dialect()) == expected
