from __future__ import annotations

from .deduplication import is_lazy_video_image
from .models import CandidateDecision, CollectedAd

INHERITED_ARTIFACTS = (
    "landing_full",
    "landing_clean",
    "landing_screenshot",
    "landing_archive",
    "fb_ad_id",
    "facebook_page_url",
    "facebook_post_url",
    "utm",
    "video",
)


class CandidateRegistry:
    def __init__(self) -> None:
        self.ads: dict[str, CollectedAd] = {}
        self._coarse_keys: dict[str, set[str]] = {}
        self._lazy_media_keys: set[str] = set()
        self._seen_fb_ad_ids: set[str] = set()
        self._duplicate_coarse_keys: set[str] = set()

    def consider(
        self,
        ad: CollectedAd,
        *,
        creative_area: int,
    ) -> CandidateDecision:
        key = ad.dedup_key()
        coarse_key = ad.coarse_key()
        lazy_media = is_lazy_video_image(
            ad.creative_img,
            has_video=ad.has_video,
            creative_area=creative_area,
        )
        if coarse_key in self._duplicate_coarse_keys:
            return self._rejected(
                ad, key, coarse_key, lazy_media, "confirmed_duplicate"
            )
        existing = self.ads.get(key)
        if existing is not None:
            if ad.feed_element_id:
                existing.feed_element_id = ad.feed_element_id
            return self._rejected(ad, key, coarse_key, lazy_media, "exact_duplicate")
        siblings = self._coarse_keys.get(coarse_key, set())
        if lazy_media and siblings:
            return self._rejected(
                ad,
                key,
                coarse_key,
                lazy_media,
                "lazy_media_duplicate",
                related_keys=tuple(sorted(siblings)),
            )
        removed, inherited = self._remove_lazy_siblings(coarse_key, lazy_media)
        if inherited:
            inherit_artifacts(ad, inherited)
        return CandidateDecision(
            ad=ad,
            key=key,
            coarse_key=coarse_key,
            lazy_media=lazy_media,
            accepted=True,
            reason="accepted",
            inherited_from=inherited,
            removed_keys=tuple(removed),
        )

    def commit(self, decision: CandidateDecision) -> None:
        if not decision.accepted:
            raise ValueError("Cannot commit a rejected candidate")
        self.ads[decision.key] = decision.ad
        self._coarse_keys.setdefault(decision.coarse_key, set()).add(decision.key)
        if decision.lazy_media:
            self._lazy_media_keys.add(decision.key)

    def register_resolved(self, decision: CandidateDecision) -> bool:
        ad = decision.ad
        if ad.fb_ad_id and ad.fb_ad_id in self._seen_fb_ad_ids:
            self._duplicate_coarse_keys.add(decision.coarse_key)
            self.remove(decision)
            return False
        if ad.fb_ad_id:
            self._seen_fb_ad_ids.add(ad.fb_ad_id)
        return True

    def remove(self, decision: CandidateDecision) -> None:
        self.ads.pop(decision.key, None)
        self._coarse_keys.get(decision.coarse_key, set()).discard(decision.key)
        self._lazy_media_keys.discard(decision.key)

    def _remove_lazy_siblings(
        self,
        coarse_key: str,
        candidate_is_lazy: bool,
    ) -> tuple[list[str], CollectedAd | None]:
        if candidate_is_lazy:
            return [], None
        removed: list[str] = []
        inherited = None
        siblings = self._coarse_keys.get(coarse_key, set())
        for old_key in list(siblings & self._lazy_media_keys):
            old = self.ads.pop(old_key, None)
            siblings.discard(old_key)
            self._lazy_media_keys.discard(old_key)
            removed.append(old_key)
            if old is not None and inherited is None:
                inherited = old
        return removed, inherited

    @staticmethod
    def _rejected(
        ad: CollectedAd,
        key: str,
        coarse_key: str,
        lazy_media: bool,
        reason: str,
        *,
        related_keys: tuple[str, ...] = (),
    ) -> CandidateDecision:
        return CandidateDecision(
            ad=ad,
            key=key,
            coarse_key=coarse_key,
            lazy_media=lazy_media,
            accepted=False,
            reason=reason,
            related_keys=related_keys,
        )


def inherit_artifacts(target: CollectedAd, source: CollectedAd) -> None:
    for attribute in INHERITED_ARTIFACTS:
        value = getattr(source, attribute)
        if value:
            setattr(target, attribute, value)
