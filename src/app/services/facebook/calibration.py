from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from sqlalchemy import select

from app.api.modules.ads.models import FacebookAd
from app.api.modules.runs.models import FacebookRun
from app.database.engine import SessionFactory
from app.settings import Config


@dataclass
class CalibrationTarget:
    url: str
    advertiser: str = ""
    displayed_domain: str = ""
    headline: str = ""
    ad_text: str = ""
    cta: str = ""
    cta_href: str | None = None
    country: str | None = None
    fb_ad_id: str | None = None
    feed_element_id: str | None = None
    facebook_page_url: str | None = None
    facebook_post_url: str | None = None
    landing_full: str | None = None
    landing_clean: str | None = None
    creative_img: str | None = None
    source: str = ""
    source_index: int | None = None
    run_id: str | None = None
    captured_at: str | None = None

    @property
    def domain_key(self) -> str:
        return _domain_key(self.landing_clean or self.url or self.displayed_domain)


def load_targets_from_ads_json(
    ads_json_paths: list[Path],
    *,
    country: str | None = None,
    limit: int = 20,
    max_per_domain: int = 2,
    include_creative_fallback: bool = False,
    require_relevant: bool = False,
) -> list[CalibrationTarget]:
    raw_ads: list[dict[str, Any]] = []
    for ads_json_path in ads_json_paths:
        path = ads_json_path.expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Expected a JSON list: {path}")
        for index, raw in enumerate(payload, start=1):
            if isinstance(raw, dict):
                if require_relevant and not _raw_is_relevant(raw):
                    continue
                item = dict(raw)
                item.setdefault("_source", str(path))
                item.setdefault("_source_index", index)
                raw_ads.append(item)

    return select_calibration_targets(
        raw_ads,
        country=country,
        limit=limit,
        max_per_domain=max_per_domain,
        include_creative_fallback=include_creative_fallback,
    )


def load_engagement_targets_from_ads_json(
    ads_json_paths: list[Path],
    *,
    country: str | None = None,
    limit: int = 1000,
) -> list[CalibrationTarget]:
    normalized_country = _normalize_filter(country)
    targets: list[CalibrationTarget] = []
    seen: set[str] = set()
    for ads_json_path in ads_json_paths:
        path = ads_json_path.expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Expected a JSON list: {path}")
        for index, raw in enumerate(payload, start=1):
            if not isinstance(raw, dict) or not _raw_is_relevant(raw):
                continue
            if (
                normalized_country
                and _normalize_filter(raw.get("country")) != normalized_country
            ):
                continue
            target = CalibrationTarget(
                url=_target_url(raw, include_creative_fallback=False),
                advertiser=str(raw.get("advertiser") or ""),
                displayed_domain=str(raw.get("displayed_domain") or ""),
                headline=str(raw.get("headline") or ""),
                ad_text=str(raw.get("ad_text") or ""),
                cta=str(raw.get("cta") or ""),
                cta_href=_clean(raw.get("cta_href")),
                country=_clean(raw.get("country")),
                fb_ad_id=_clean(raw.get("fb_ad_id")),
                feed_element_id=_clean(raw.get("feed_element_id")),
                facebook_page_url=_clean(raw.get("facebook_page_url")),
                facebook_post_url=_clean(raw.get("facebook_post_url")),
                landing_full=_clean(raw.get("landing_full")),
                landing_clean=_clean(raw.get("landing_clean")),
                creative_img=_clean(raw.get("creative_img")),
                source=str(path),
                source_index=index,
                run_id=_clean(raw.get("run_id")),
                captured_at=_clean(raw.get("captured_at")),
            )
            key = str(
                target.fb_ad_id
                or target.landing_clean
                or "\x1f".join((
                    target.advertiser.casefold(),
                    target.displayed_domain.casefold(),
                    target.headline.casefold(),
                    target.ad_text.casefold(),
                ))
            )
            if not key.strip("\x1f") or key in seen:
                continue
            seen.add(key)
            targets.append(target)
            if len(targets) >= limit:
                return targets
    return targets


def load_saved_facebook_targets_from_ads_json(
    ads_json_paths: list[Path],
    *,
    country: str | None = None,
    limit: int = 20,
    excluded_urls: set[str] | None = None,
    include_direct_offers: bool = False,
) -> list[CalibrationTarget]:
    """Load relevant saved posts, optionally retaining direct-offer fallbacks."""
    if limit <= 0:
        return []
    normalized_country = _normalize_filter(country)
    excluded = excluded_urls or set()
    targets: list[CalibrationTarget] = []
    seen_targets: set[str] = set()
    for ads_json_path in ads_json_paths:
        path = ads_json_path.expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Expected a JSON list: {path}")
        for index, raw in enumerate(payload, start=1):
            if not isinstance(raw, dict) or not _raw_is_relevant(raw):
                continue
            if (
                normalized_country
                and _normalize_filter(raw.get("country")) != normalized_country
            ):
                continue
            post_url = _valid_facebook_post_url(raw.get("facebook_post_url"))
            cta_href = _clean(raw.get("cta_href"))
            landing_full = _clean(raw.get("landing_full"))
            landing_clean = _clean(raw.get("landing_clean"))
            if post_url in excluded:
                post_url = ""
            if not post_url and not (
                include_direct_offers and (landing_full or cta_href or landing_clean)
            ):
                continue
            target_key = str(
                post_url
                or raw.get("fb_ad_id")
                or landing_clean
                or cta_href
                or landing_full
            )
            if not target_key or target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            targets.append(CalibrationTarget(
                url=post_url or landing_full or cta_href or landing_clean or "",
                advertiser=str(raw.get("advertiser") or ""),
                displayed_domain=str(raw.get("displayed_domain") or ""),
                headline=str(raw.get("headline") or ""),
                ad_text=str(raw.get("ad_text") or ""),
                cta=str(raw.get("cta") or ""),
                cta_href=cta_href,
                country=_clean(raw.get("country")),
                fb_ad_id=_clean(raw.get("fb_ad_id")),
                feed_element_id=None,
                facebook_page_url=_clean(raw.get("facebook_page_url")),
                facebook_post_url=post_url or None,
                landing_full=landing_full,
                landing_clean=landing_clean,
                creative_img=_clean(raw.get("creative_img")),
                source=str(path),
                source_index=index,
                run_id=_clean(raw.get("run_id")),
                captured_at=_clean(raw.get("captured_at")),
            ))
            if len(targets) >= limit:
                return targets
    return targets


def rotate_calibration_targets(
    targets: list[CalibrationTarget],
    offset: int,
) -> list[CalibrationTarget]:
    if not targets:
        return []
    normalized_offset = max(0, offset) % len(targets)
    if normalized_offset == 0:
        return list(targets)
    return [*targets[normalized_offset:], *targets[:normalized_offset]]


async def load_targets_from_db(
    config: Config,
    *,
    country: str | None = None,
    octo_profile_uuid: str | None = None,
    run_id: UUID | None = None,
    limit: int = 20,
    max_per_domain: int = 2,
    include_creative_fallback: bool = False,
) -> list[CalibrationTarget]:
    fetch_limit = max(limit * 8, limit, 50)
    async with SessionFactory() as session:
        stmt = (
            select(FacebookAd, FacebookRun)
            .join(FacebookRun, FacebookAd.run_id == FacebookRun.id)
            .order_by(
                FacebookAd.captured_at.desc().nullslast(),
                FacebookAd.created_at.desc(),
            )
            .limit(fetch_limit)
        )
        if country:
            stmt = stmt.where(FacebookAd.country == country)
        if octo_profile_uuid:
            stmt = stmt.where(FacebookRun.octo_profile_uuid == octo_profile_uuid)
        if run_id:
            stmt = stmt.where(FacebookAd.run_id == run_id)
        if not include_creative_fallback:
            stmt = stmt.where(FacebookAd.landing_full.is_not(None))

        rows = (await session.execute(stmt)).all()

    raw_ads = [_raw_from_db_row(ad, run, config) for ad, run in rows]
    return select_calibration_targets(
        raw_ads,
        country=None,
        limit=limit,
        max_per_domain=max_per_domain,
        include_creative_fallback=include_creative_fallback,
    )


def select_calibration_targets(
    raw_ads: list[dict[str, Any]],
    *,
    country: str | None = None,
    limit: int = 20,
    max_per_domain: int = 2,
    include_creative_fallback: bool = False,
) -> list[CalibrationTarget]:
    normalized_country = _normalize_filter(country)
    candidates: list[tuple[int, datetime, CalibrationTarget]] = []
    seen_keys: set[str] = set()
    seen_landing_keys: set[str] = set()

    for raw in raw_ads:
        if normalized_country and _normalize_filter(raw.get("country")) != normalized_country:
            continue

        url = _target_url(raw, include_creative_fallback=include_creative_fallback)
        if not url:
            continue

        target = CalibrationTarget(
            url=url,
            advertiser=str(raw.get("advertiser") or ""),
            displayed_domain=str(raw.get("displayed_domain") or ""),
            headline=str(raw.get("headline") or ""),
            ad_text=str(raw.get("ad_text") or ""),
            cta=str(raw.get("cta") or ""),
            cta_href=_clean(raw.get("cta_href")),
            country=_clean(raw.get("country")),
            fb_ad_id=_clean(raw.get("fb_ad_id")),
            feed_element_id=_clean(raw.get("feed_element_id")),
            facebook_page_url=_clean(raw.get("facebook_page_url")),
            facebook_post_url=_clean(raw.get("facebook_post_url")),
            landing_full=_clean(raw.get("landing_full")),
            landing_clean=_clean(raw.get("landing_clean")),
            creative_img=_clean(raw.get("creative_img")),
            source=str(raw.get("_source") or ""),
            source_index=_int_or_none(raw.get("_source_index") or raw.get("source_index")),
            run_id=_clean(raw.get("run_id")),
            captured_at=_clean(raw.get("captured_at")),
        )
        unique_key = _unique_key(target)
        landing_key = target.landing_clean or target.url
        if (
            unique_key in seen_keys
            or (not target.fb_ad_id and landing_key in seen_landing_keys)
        ):
            continue
        seen_keys.add(unique_key)
        seen_landing_keys.add(landing_key)
        candidates.append((_target_score(raw), _captured_at(raw), target))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return _limit_by_domain(
        [target for _, _, target in candidates],
        limit=limit,
        max_per_domain=max_per_domain,
    )


def write_targets(path: Path, targets: list[CalibrationTarget]) -> None:
    _write_json_atomic(path, [asdict(target) for target in targets])


def write_json(path: Path, payload: Any) -> None:
    _write_json_atomic(path, payload)


def quarantined_facebook_post_urls(
    path: Path | None,
    *,
    now: datetime | None = None,
) -> set[str]:
    payload = _load_target_health(path)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    quarantined: set[str] = set()
    for url, raw in payload.get("targets", {}).items():
        if not isinstance(raw, dict):
            continue
        until = _aware_datetime(raw.get("quarantined_until"))
        if until is not None and until > current:
            quarantined.add(str(url))
    return quarantined


def record_facebook_post_target_result(
    path: Path | None,
    result: dict[str, Any],
    *,
    now: datetime | None = None,
    failure_threshold: int = 2,
    quarantine_days: int = 7,
) -> None:
    if path is None:
        return
    url = _clean(result.get("url"))
    if not url:
        return
    payload = _load_target_health(path)
    targets = payload.setdefault("targets", {})
    if result.get("ok") is True:
        if targets.pop(url, None) is not None:
            payload["updated_at"] = (now or datetime.now(UTC)).isoformat()
            _write_json_atomic(path, payload)
        return
    match = result.get("match")
    if not isinstance(match, dict) or match.get("status") != "post_not_found":
        return

    current = (now or datetime.now(UTC)).astimezone(UTC)
    previous = targets.get(url) if isinstance(targets.get(url), dict) else {}
    failures = max(0, _int_or_none(previous.get("consecutive_failures")) or 0) + 1
    record = {
        "consecutive_failures": failures,
        "last_failed_at": current.isoformat(),
        "last_status": "post_not_found",
    }
    if failures >= max(1, failure_threshold):
        record["quarantined_until"] = (
            current + timedelta(days=max(1, quarantine_days))
        ).isoformat()
    targets[url] = record
    payload["updated_at"] = current.isoformat()
    _write_json_atomic(path, payload)


def append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    os.chmod(path, 0o600)


def _raw_from_db_row(ad: FacebookAd, run: FacebookRun, config: Config) -> dict[str, Any]:
    return {
        "run_id": str(ad.run_id),
        "source_index": ad.source_index,
        "advertiser": ad.advertiser,
        "displayed_domain": ad.displayed_domain,
        "headline": ad.headline,
        "ad_text": ad.ad_text,
        "cta": ad.cta,
        "cta_href": None,
        "country": ad.country or run.profile_country or config.facebook.default_country,
        "fb_ad_id": ad.fb_ad_id,
        "feed_element_id": None,
        "facebook_page_url": None,
        "facebook_post_url": None,
        "landing_full": ad.landing_full,
        "landing_clean": ad.landing_clean,
        "creative_img": ad.creative_img,
        "captured_at": ad.captured_at.isoformat() if ad.captured_at else None,
        "_source": "db",
    }


def _target_url(
    raw: dict[str, Any],
    *,
    include_creative_fallback: bool,
) -> str:
    for key in ("landing_full", "landing_clean"):
        value = _clean(raw.get(key))
        if value:
            return value
    if include_creative_fallback:
        return _clean(raw.get("creative_img")) or ""
    return ""


def _valid_facebook_post_url(value: Any) -> str:
    url = _clean(value)
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if "posts" in parts:
        index = parts.index("posts")
        return url if index > 0 and index + 1 < len(parts) else ""
    query = parse_qs(parsed.query)
    if (
        parsed.path.rstrip("/").endswith(("story.php", "permalink.php"))
        and (query.get("story_fbid") or [""])[0]
        and (query.get("id") or [""])[0]
    ):
        return url
    else:
        return ""


def _target_score(raw: dict[str, Any]) -> int:
    score = 0
    if raw.get("landing_full"):
        score += 5
    if raw.get("fb_ad_id"):
        score += 2
    if raw.get("headline") or raw.get("ad_text"):
        score += 1
    if raw.get("has_video"):
        score += 1
    return score


def _limit_by_domain(
    targets: list[CalibrationTarget],
    *,
    limit: int,
    max_per_domain: int,
) -> list[CalibrationTarget]:
    if limit <= 0:
        return []

    domain_counts: dict[str, int] = {}
    selected: list[CalibrationTarget] = []
    overflow: list[CalibrationTarget] = []
    per_domain = max(1, max_per_domain)

    for target in targets:
        domain = target.domain_key or target.displayed_domain or target.url
        count = domain_counts.get(domain, 0)
        if count < per_domain:
            selected.append(target)
            domain_counts[domain] = count + 1
        else:
            overflow.append(target)
        if len(selected) >= limit:
            return selected

    for target in overflow:
        selected.append(target)
        if len(selected) >= limit:
            break
    return selected


def _unique_key(target: CalibrationTarget) -> str:
    if target.fb_ad_id:
        return f"fb_ad_id:{target.fb_ad_id}"
    clean = target.landing_clean or ""
    if clean:
        return f"landing_clean:{clean}"
    return f"url:{target.url}"


def _domain_key(value: str) -> str:
    if not value:
        return ""
    if "://" not in value and "." in value:
        value = f"https://{value}"
    try:
        host = urlsplit(value).netloc or urlsplit(f"https://{value}").netloc
    except ValueError:
        return value.lower().strip()
    return host.lower().removeprefix("www.")


def _captured_at(raw: dict[str, Any]) -> datetime:
    value = _clean(raw.get("captured_at"))
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def _aware_datetime(value: Any) -> datetime | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_target_health(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"version": 1, "targets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "targets": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("targets"), dict):
        return {"version": 1, "targets": {}}
    payload.setdefault("version", 1)
    return payload


def _normalize_filter(value: Any) -> str | None:
    cleaned = _clean(value)
    return cleaned.casefold() if cleaned else None


def _raw_is_relevant(raw: dict[str, Any]) -> bool:
    if raw.get("relevant") is True:
        return True
    relevance = raw.get("relevance")
    if isinstance(relevance, dict):
        return str(relevance.get("result") or "").casefold() == "relevant"
    if isinstance(relevance, str):
        return relevance.casefold() == "relevant"
    return False


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.chmod(tmp, 0o600)
    tmp.replace(path)
