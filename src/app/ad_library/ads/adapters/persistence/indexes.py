from sqlalchemy import Index, Table, and_, func

GEO_FACEBOOK_ID_INDEX = "facebook_ads_geo_fb_ad_id_uidx"


def register_ad_indexes(table: Table) -> None:
    country = table.c.country
    facebook_id = table.c.fb_ad_id
    populated_identity = and_(
        country.is_not(None),
        country != "",
        facebook_id.is_not(None),
        facebook_id != "",
    )
    Index(
        GEO_FACEBOOK_ID_INDEX,
        func.lower(country),
        facebook_id,
        unique=True,
        postgresql_where=populated_identity,
        sqlite_where=populated_identity,
    )
