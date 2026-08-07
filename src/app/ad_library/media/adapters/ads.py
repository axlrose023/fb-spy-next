from uuid import UUID

from app.ad_library.ads import AdReader

from ..models import MEDIA_SPECS, MediaKind


class AdMediaReader:
    def __init__(self, ads: AdReader) -> None:
        self._ads = ads

    async def reference_for(self, ad_id: UUID, kind: MediaKind) -> str | None:
        ad = await self._ads.get(ad_id)
        if ad is None:
            return None
        reference = getattr(ad, MEDIA_SPECS[kind].model_attribute)
        return str(reference) if reference else None


LegacyAdMediaReader = AdMediaReader
