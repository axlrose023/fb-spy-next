from uuid import UUID

from app.api.modules.ads.gateway import FacebookAdGateway

from ..models import MEDIA_SPECS, MediaKind


class LegacyAdMediaReader:
    def __init__(self, ads: FacebookAdGateway) -> None:
        self._ads = ads

    async def reference_for(self, ad_id: UUID, kind: MediaKind) -> str | None:
        ad = await self._ads.get_by_id(ad_id)
        if ad is None:
            return None
        reference = getattr(ad, MEDIA_SPECS[kind].model_attribute)
        return str(reference) if reference else None
