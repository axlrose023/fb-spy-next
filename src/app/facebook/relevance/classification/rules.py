from __future__ import annotations

from typing import Any

from .exclusion_terms import (
    ENTERPRISE_TECH_TERMS,
    FINANCE_EDUCATION_TERMS,
    GAMBLING_ACQUISITION_TERMS,
    GAMBLING_HOST_MARKERS,
    GAMBLING_TERMS,
    GAMING_TERMS,
    HEALTH_PRODUCT_TERMS,
    MOBILE_ATTRIBUTION_HOSTS,
)
from .matching import (
    advertiser_matches_domain,
    contains_any_term,
    has_percentage_bonus,
    hostname,
)
from .target_terms import (
    ALLOWED_RELEVANT_CATEGORIES,
    FAKE_NEWS_FINANCE_PRELANDER_TERMS,
    GENERIC_AI_TERMS,
    GENERIC_INCOME_TERMS,
    HARD_FINANCE_TERMS,
    RAW_SCAM_EVIDENCE_TERMS,
    STRONG_SCAM_EVIDENCE_TERMS,
    STRONG_TARGET_ANCHOR_TERMS,
    SUPPORTING_ONLY_FUNNEL_TERMS,
)


def _rejected(reason: str) -> dict[str, Any]:
    return {"result": "not_relevant", "reason": reason}


def _model_text(data: dict[str, Any]) -> str:
    parts = [
        str(value)
        for value in (data.get("reason"), data.get("product"), data.get("category"))
        if value
    ]
    grey_signals = data.get("grey_signals")
    if isinstance(grey_signals, list):
        parts.extend(str(item) for item in grey_signals if item)
    return " ".join(parts).casefold()


def _raw_text(raw: dict[str, Any]) -> str:
    fields = (
        "advertiser",
        "displayed_domain",
        "headline",
        "ad_text",
        "cta",
        "cta_href",
        "landing_full",
        "landing_clean",
    )
    return " ".join(str(raw[key]) for key in fields if raw.get(key)).casefold()


def _is_mobile_attribution_host(host: str) -> bool:
    return any(
        host == known_host or host.endswith(f".{known_host}")
        for known_host in MOBILE_ATTRIBUTION_HOSTS
    )


def apply_scope_guards(raw: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic exclusions where the model is often too permissive."""
    if data.get("result") != "relevant":
        return data

    raw_text = _raw_text(raw)
    model_text = _model_text(data)
    text = " ".join((raw_text, model_text))
    category = str(data.get("category") or "").strip().casefold()
    displayed_host = hostname(
        raw.get("displayed_domain")
        or raw.get("landing_clean")
        or raw.get("landing_full")
    )
    has_gambling = (
        contains_any_term(text, GAMBLING_TERMS)
        or contains_any_term(text, GAMBLING_ACQUISITION_TERMS)
        or has_percentage_bonus(text)
        or any(marker in displayed_host for marker in GAMBLING_HOST_MARKERS)
    )
    raw_has_finance = contains_any_term(raw_text, HARD_FINANCE_TERMS)
    model_has_finance = contains_any_term(model_text, HARD_FINANCE_TERMS)
    raw_has_fake_news = contains_any_term(
        raw_text, FAKE_NEWS_FINANCE_PRELANDER_TERMS
    )
    raw_has_scam = contains_any_term(raw_text, RAW_SCAM_EVIDENCE_TERMS)
    has_generic_ai_income = contains_any_term(
        raw_text, GENERIC_AI_TERMS
    ) and contains_any_term(raw_text, GENERIC_INCOME_TERMS)
    has_supporting_only = contains_any_term(text, SUPPORTING_ONLY_FUNNEL_TERMS)
    has_target_anchor = contains_any_term(text, STRONG_TARGET_ANCHOR_TERMS)

    if category and category not in ALLOWED_RELEVANT_CATEGORIES:
        return _rejected(
            "Out-of-scope category: only grey finance, crypto, forex, trading, "
            "investment, yield, broker, money-system, or hidden finance "
            "prelander funnels are relevant."
        )
    if contains_any_term(text, HEALTH_PRODUCT_TERMS) and not raw_has_finance:
        return _rejected(
            "Health/nutra/medical product funnel without an evidenced finance, "
            "crypto, trading, yield, or investment offer."
        )
    if (
        contains_any_term(text, ENTERPRISE_TECH_TERMS)
        and not raw_has_finance
        and not raw_has_fake_news
    ):
        return _rejected(
            "Corporate technology, cloud-partner, or professional-skilling "
            "campaign without a finance-scam offer."
        )
    if contains_any_term(text, GAMING_TERMS) and not raw_has_finance:
        return _rejected(
            "Gaming product, virtual item, or in-game currency offer without "
            "a real finance, trading, crypto, or investment funnel."
        )
    if (
        _is_mobile_attribution_host(displayed_host)
        and not raw_has_finance
        and not raw_has_fake_news
    ):
        return _rejected(
            "Known mobile attribution/deep-link host is not evidence of brand "
            "impersonation or a grey finance funnel."
        )
    if contains_any_term(text, FINANCE_EDUCATION_TERMS) and not contains_any_term(
        text, STRONG_SCAM_EVIDENCE_TERMS
    ):
        return _rejected(
            "Ordinary branded finance/trading education without fake-news, "
            "impersonation, guaranteed returns, or another strong scam-funnel signal."
        )
    if (
        (
            raw_has_finance
            or model_has_finance
            or category in {"crypto", "forex", "trading", "broker", "investing", "yield"}
        )
        and advertiser_matches_domain(
            raw.get("advertiser"),
            raw.get("displayed_domain") or raw.get("landing_clean"),
        )
        and not raw_has_fake_news
        and not raw_has_scam
    ):
        return _rejected(
            "Consistently branded broker, prop-firm, or trading-service "
            "promotion without fake-news impersonation, a hidden prelander, "
            "or a guaranteed-return scam claim."
        )
    if has_gambling and not raw_has_finance and not raw_has_fake_news:
        return _rejected(
            "Pure casino/gambling/betting offer without a hard crypto, forex, "
            "trading, or yield scam signal."
        )
    if (
        has_generic_ai_income
        and not raw_has_finance
        and not raw_has_fake_news
        and not has_target_anchor
    ):
        return _rejected(
            "Generic AI/webinar/online-income offer without a hard finance, "
            "crypto, forex, trading, signal, broker-deposit, or fake-news "
            "finance-prelander signal in the ad itself."
        )
    if has_supporting_only and not has_target_anchor:
        return _rejected(
            "Generic redirect/tracking/register-style funnel without a strong "
            "finance, bank/state, public-figure, fake-news scandal, or "
            "investment-scam anchor."
        )
    return data
