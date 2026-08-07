from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.clients.gemini import GeminiClient
from app.settings import Config

logger = logging.getLogger(__name__)

_GAMBLING_TERMS = (
    "casino",
    "casino-style",
    "gambling",
    "gambling-style",
    "sports betting",
    "sportsbook",
    "betting",
    "bet",
    "bahis",
    "texbet",
    "nesine",
    "casno",
)

_GAMBLING_HOST_MARKERS = (
    "casino",
    "sportsbook",
    "betting",
    "coinbet",
    "texbet",
    "1xbet",
    "cajero",
    "registrogratis",
    "goldenparatodos",
    "latinoparatodos",
)

_GAMBLING_ACQUISITION_TERMS = (
    "cajero imperial",
    "todas las plataformas",
    "multiplataforma",
    "proveedor de plataformas",
    "carga por whatsapp",
    "golden para todos",
    "latino para todos",
)

_HARD_FINANCE_TERMS = (
    "crypto",
    "kripto",
    "bitcoin",
    "btc",
    "forex",
    "trading",
    "trade",
    "trader",
    "borsa",
    "broker",
    "mt4",
    "mt5",
    "staking",
    "yield",
    "copy-trading",
    "prop firm",
    "signal",
    "sinyal",
    "hisse",
    "yatırım",
)

_GENERIC_AI_TERMS = (
    "ai",
    "artificial intelligence",
    "yapay zeka",
    "yapay zekâ",
    "chatgpt",
)

_GENERIC_INCOME_TERMS = (
    "income",
    "monthly income",
    "earn",
    "earning",
    "make money",
    "online income",
    "kazanç",
    "kazanan",
    "kazanmak",
    "para kazan",
    "$",
    "finansal özgürlük",
    "financial freedom",
)

_ALLOWED_RELEVANT_CATEGORIES = {
    "crypto",
    "forex",
    "trading",
    "broker",
    "investing",
    "yield",
    "make_money",
    "other_relevant",
}

_HEALTH_PRODUCT_TERMS = (
    "supplement",
    "nutritional product",
    "nutrition support",
    "nutra",
    "miracle cure",
    "miracle treatment",
    "disease reversal",
    "reverses alzheimer",
    "alzheimer",
    "dementia",
    "brain support",
    "kidney cleaning",
    "neypro",
    "vapour rub",
    "vaporub",
)

_FINANCE_EDUCATION_TERMS = (
    "education",
    "educational",
    "training",
    "course",
    "academy",
    "ebook",
    "e-book",
    "lesson",
    "lessons",
    "lección",
    "lecciones",
    "workshop",
    "seminar",
    "learn forex",
    "learning the market",
    "trading education",
    "trading course",
    "students",
)

_ENTERPRISE_TECH_TERMS = (
    "microsoft",
    "cloud partner",
    "partner program",
    "partner skilling",
    "skilling hub",
    "market-ready solutions",
    "enterprise software",
    "developer training",
)

_GAMING_TERMS = (
    "gaming",
    "video game",
    "in-game",
    "arena breakout",
    "game currency",
    "virtual currency",
    "game credits",
)

_MOBILE_ATTRIBUTION_HOSTS = {
    "adj.st",
    "app.adjust.com",
    "onelink.me",
    "app.link",
}

_RAW_SCAM_EVIDENCE_TERMS = (
    "fake news",
    "fake-news",
    "breaking news",
    "guaranteed profit",
    "guaranteed return",
    "unrealistic return",
    "minimum deposit",
    "secret system",
    "public funds",
    "government program",
    "impersonation",
)

_STRONG_SCAM_EVIDENCE_TERMS = (
    "fake news",
    "fake-news",
    "fake tv",
    "fake-tv",
    "impersonation",
    "public-figure bait",
    "public figure bait",
    "government program",
    "guaranteed return",
    "guaranteed profit",
    "daily return",
    "high return",
    "unrealistic return",
    "minimum deposit",
    "passive income",
    "secret system",
    "throwaway domain",
    "mismatched domain",
)

_SUPPORTING_ONLY_FUNNEL_TERMS = (
    "throwaway domain",
    "tracking",
    "facebook campaign",
    "registration",
    "register",
    "kaydol",
    "kayıt",
    "kolay başlangıç",
    "easy start",
    "method",
    "yöntem",
    "three months",
    "üç aydır",
)

_FAKE_NEWS_FINANCE_PRELANDER_TERMS = (
    "breaking news",
    "fake news",
    "skandal",
    "scandal",
    "sensational",
    "ifşa",
    "bakan",
    "başkan",
    "minister",
    "politician",
    "political figure",
    "political event",
    "political bait",
    "parliament",
    "party logo",
    "chp",
    "anka",
    "police",
    "arrest",
    "şimşek",
    "mikrofon",
    "microphone",
    "truth revealed",
    "pravda",
    "uniklé",
    "česko",
    "cesko",
    "public funds",
    "halka ait",
    "stolen funds",
    "corruption",
    "yolsuzluk",
    "government",
    "devlet",
    "bank",
    "banka",
    "robbery",
    "theft",
    "soyğun",
    "soygun",
    "çald*",
    "cald*",
    "hakkım olan",
    "hakkim olan",
)

_GUARD_HARD_FINANCE_TERMS = tuple(
    term for term in _HARD_FINANCE_TERMS if term != "signal"
) + (
    "signal group",
    "trading signal",
    "telegram signal",
)

_STRONG_TARGET_ANCHOR_TERMS = (
    *_GUARD_HARD_FINANCE_TERMS,
    *_FAKE_NEWS_FINANCE_PRELANDER_TERMS,
    "public figure",
    "famous person",
    "celebrity",
    "president",
    "prime minister",
    "tv presenter",
    "presenter",
    "journalist",
    "governor",
    "mayor",
    "central bank",
    "bangko sentral",
    "gma network",
    "fast talk",
    "boy abunda",
    "live tv sensation",
    "news studio",
    "tv-news",
    "banknote",
    "banknotes",
    "cash",
    "balance",
    "bakiye",
    "finans*",
    "investment opportunity",
    "investment opportunities",
    "tl",
    "₺",
    "tpao",
    "bsp",
    "caticlan city",
    "government app",
    "official app",
    "iş bankası",
    "is bankasi",
    "vakıf",
    "vakif",
    "ziraat",
    "atatürk",
    "ataturk",
    "şimşek",
    "simsek",
    "mansur",
    "sedat",
    "levent",
    "acun",
    "saliha",
)

_TEXT_SCOPE = """\
Classify whether this Facebook ad belongs to a narrow grey/scam finance buyer-funnel watchlist.

This is NOT a general finance or general scam classifier, nor a broad crypto,
forex, broker, investing, health, gambling, dating, or e-commerce classifier.
Mark RELEVANT only when the ad fits
one of these target classes AND has clear grey/scam media-buyer funnel signals:
1. Visible finance-scam offer: crypto, forex, trading, investing, yield, broker deposits, signal groups, copy-trading, passive income from a financial/investment system, payouts from an investment/trading system, or a vague high-return money system with explicit financial/profit/deposit/payout amounts or finance context.
2. Hidden-offer fake-news prelander: a sensational news/TV/current-affairs/public-figure story that is very likely a paid social prelander for a finance/crypto/investment scam funnel even when the final offer is hidden behind the click.

Important hidden-offer prelander rule:
- Mark RELEVANT even when the first Facebook card does not visibly mention crypto, trading, or investing if it combines BOTH:
  a) fake-news/public-figure bait: politicians, ministers, presidents, TV presenters, journalists, celebrities, bank/state figures, parliament, police/court/arrest scenes, "breaking news", live-broadcast scandal, "microphone left on", "truth revealed", "country shocked", leaked/secret information, corruption, public money, bank/economic scandal, or similar sensational current-affairs bait; AND
  b) performance-funnel/grey signals: suspicious redirect/tracking/affiliate/autologin URL, throwaway or mismatched domain, Facebook campaign parameters, ad_id/pixel/token parameters, registration/lead-gen CTA, fake video-play creative, or advertiser/domain/brand mismatch.
- These fake-news public-figure prelanders are a primary target class because finance scam buyers often hide the crypto/trading/investment offer until after the click.
- Generalize from Turkish and Czech examples: Turkish "KAYIT" ads with TL amounts, banks, politicians, parliament, or "microphone/scandal" hooks; Czech fake ČT/news-style ads about politicians, prime ministers, ministers, prison/arrest, "unique information", or "truth revealed" on random domains.
- Generalize from Philippine examples: fake or repurposed GMA Network/Fast Talk/news-show creatives with a governor, mayor, BSP/central-bank official, TV host, business leader, staged scandal or medical emergency; and fake Caticlan/local-government app creatives using a public/business figure plus "click the link below." Treat these as suspected hidden finance prelanders only when they also have a random/mismatched domain, app/registration CTA, tracking, advertiser mismatch, or similar performance-funnel evidence.
- Do NOT treat a random domain, Facebook tracking parameters, a generic "register/learn more" CTA, or an ordinary person talking in a video as enough evidence by itself. The ad still needs a strong target anchor: finance/profit/bank/state/official/public-figure/fake-news scandal/police/arrest/parliament/TV-news evidence.

Grey/scam signals include:
- fake-news or advertorial style, "breaking news", "everyone is talking", scandal/confession stories, or public-figure/celebrity bait
- impersonation or suspicious use of banks, state programs, politicians, famous people, or large brands
- promises of payments, monthly income, fast profit, guaranteed/simple earnings, passive income, financial freedom, or unusually high returns
- AI/algorithmic/automated/quantum trading bot funnels that push registration, deposit, or profit chasing
- vague lead-gen pages, quiz/registration funnels, affiliate/autologin URLs, suspicious redirects, throwaway domains, or mismatched advertiser/domain/brand
- clickbait that pushes consumers into an unregulated investment, crypto, trading, or money-making flow

Generic make-money clarification:
- Do NOT mark an ad relevant only because it promises money, online income, business growth, AI income, entrepreneurship income, webinar income, or a guide to earning online. It must be specifically tied to finance, investing, crypto, forex, trading, yield, signal groups, broker deposits, copy-trading, or match the fake-news finance prelander exception.

Mark NOT RELEVANT for:
- normal political/news/media ads from credible or consistent publishers when there is no suspicious redirect, throwaway lead-gen domain, registration funnel, public-figure scam framing, or hidden finance-scam prelander pattern
- ordinary UGC, street-interview, selfie, lifestyle, emotional TV clips, or generic "method/easy start/three months/register now" ads when the visible creative and metadata do not show finance, investing, crypto, trading, bank/state/public-figure bait, or a fake-news scandal/current-affairs prelander
- legitimate or regulated-looking brokers, prop firms, crypto exchanges, banks, funds, portfolio managers, market-data apps, or trading education when there is no clear grey/scam signal
- prop/funded account challenge promos, discount codes, BOGO offers, refundable challenge fees, "get funded" ads, or demo-account reward ads unless they also use fake-news/public-figure bait, guaranteed profit, deceptive impersonation, or suspicious scam prelander tactics
- stock-picking apps, portfolio research tools, market-data apps, or newsletter-style "stock pick" ads when they look like a normal branded app/service and do not use fake-news impersonation, throwaway lead-gen pages, Telegram/signal funnels, or unrealistic guaranteed-return claims
- normal broker commodity/gold/forex ads, including "trade gold/oil/forex" CTAs, if they are broker-brand ads without fake-news, public-figure bait, suspicious redirects, or exaggerated profit promises
- normal branded broker, CFD, prop-firm, funded-account, or trading-platform promotions when the advertiser and destination are the same brand and there is no fake-news impersonation, hidden prelander, or guaranteed-return scam claim; discounts, daily payouts, profit splits, challenge refunds, leverage, sports giveaways, and celebrity-branded prizes alone are not enough
- corporate technology, cloud-partner, developer-skilling, certification, enterprise-software, or Microsoft partner-program ads, even when they discuss business revenue or link to a campaign microsite
- video-game stores, virtual items, in-game currency, game "bonds", balance top-ups, refunds, or gaming rewards; financial words used only inside a game are not finance-scam evidence
- legitimate payment-app campaigns that use known mobile attribution/deep-link domains; an attribution hostname alone is not brand impersonation or a suspicious redirect
- ordinary banking, insurance, payments, employee benefits, cards, payroll, accounting, ERP, tax, B2B SaaS
- generic business consulting, CIO/IT services, marketing agencies, analytics, competitor intelligence
- generic AI/business/webinar/make-money-online courses or guides when they are not specifically finance, investing, crypto, forex, trading, yield, signals, or a fake-news finance prelander
- hotels, travel, cars, telecom, cosmetics, retail, food, furniture, pet products, music, education, jobs
- health/nutra/medical products and funnels, including fake medical advertorials, hospital/doctor/news impersonation, miracle cures, disease-reversal claims, or fear-based medical creatives, unless the same funnel explicitly reveals a finance/investment offer
- pure casino/gambling/sports betting, betting bonuses, trial bonuses, "win money" offers, or casino deposit/payout claims unless they clearly include crypto/investment/trading/yield scam messaging
- dating/chat acquisition, including AI/stock-person creatives, unless the same funnel explicitly reveals a finance/investment offer
- generic e-commerce, turnkey-business, coaching, or entrepreneurship offers without a specific finance/investment target
- ordinary branded forex/trading education, courses, academies, seminars, or market-learning communities when they only promise learning, opportunity, or financial freedom and have no fake-news/public-figure impersonation, guaranteed or exaggerated returns, hidden investment platform, suspicious domain, or similar scam evidence
- trading ebooks, lessons, workshops, and educational guides when they sell training or content rather than a deceptive investment/deposit funnel
- normal investment funds or corporate capital firms if the pitch is B2B/institutional or brand-building rather than a scammy consumer funnel

Be very strict. The default is NOT RELEVANT.
Do NOT mark an ad relevant only because it mentions forex, crypto, trading, investment, broker, capital, CIO, benefits, insurance, finance, money, online income, AI income, casino winnings, or betting payouts.
Do NOT mark an ad relevant only because it uses a throwaway domain, Facebook campaign parameters, ad_id/pixel parameters, affiliate-style tracking, or a registration CTA; those are supporting signals, not the target class.
If the ad looks like a normal financial service, reject it even if users can trade or invest there.
If the ad is health/nutra/medical, reject it even when it is deceptive, impersonates a hospital/news outlet/public figure, or makes miracle claims, unless a finance/investment offer is also evidenced.
If the ad is only gambling/casino/betting, reject it even if it promises income, winnings, bonuses, deposits, or payouts.
If the ad is a generic AI, entrepreneurship, webinar, or online-income offer, reject it even if it promises a large monthly income, unless it is specifically a financial/crypto/trading/yield offer or a fake-news finance prelander.
Do NOT reject fake-news public-figure prelanders just because the final investment/crypto/trading offer is not visible in the first Facebook card; if they match the hidden-offer prelander rule above, mark them relevant.
"""

_RESPONSE_FORMAT = """\
Respond with ONLY a JSON object.

If relevant:
{"result":"relevant","reason":"one sentence","advertiser":"name","product":"short product","category":"crypto|forex|trading|broker|investing|yield|make_money|other_relevant","grey_signals":["short evidence"],"language":"detected language"}

If not relevant:
{"result":"not_relevant","reason":"one sentence"}

If there is not enough evidence:
{"result":"not_relevant","reason":"Insufficient evidence of a grey finance, crypto, trading, or investment-scam offer."}
"""

_PREFILTER_RESPONSE_FORMAT = """\
Respond with ONLY a JSON object.

Use "relevant" only when the Facebook card itself contains enough evidence to
safely allow active profile actions such as playing its video or clicking its
CTA.

Use "not_relevant" when the visible card is clearly an out-of-scope product,
service, publisher, or vertical.

Use "uncertain" when the card could plausibly be a hidden finance-scam
prelander but the visible card is not strong enough to safely click without
checking the landing in an isolated browser.

{"result":"relevant|not_relevant|uncertain","reason":"one sentence"}
"""

TEXT_PROMPT = f"""\
Analyze this Facebook ad metadata and visible text.

{_TEXT_SCOPE}

{_RESPONSE_FORMAT}

Examples:
{{"result":"relevant","reason":"The ad uses a public-figure confession hook to push users into a suspicious investment registration funnel.","advertiser":"Daily Finance News","product":"Investment lead-gen funnel","category":"make_money","grey_signals":["public-figure bait","fake-news style","registration funnel"],"language":"English"}}
{{"result":"relevant","reason":"The ad uses a fake breaking-news scandal about public funds and a finance minister on a throwaway tracking domain, which is a classic finance-scam prelander even though the final offer is hidden behind the click.","advertiser":"LiveNews","product":"Fake-news finance prelander","category":"other_relevant","grey_signals":["fake-news style","public-figure bait","public funds scandal","throwaway tracking domain"],"language":"Turkish"}}
{{"result":"relevant","reason":"The ad uses a Turkish politician/economic-news video with TL amounts, a registration CTA, and a random domain, matching the grey finance lead-gen pattern.","advertiser":"Turkiye Ekonomi Gundemi","product":"Finance lead-gen prelander","category":"other_relevant","grey_signals":["politician bait","TL amount claims","registration CTA","throwaway domain"],"language":"Turkish"}}
{{"result":"relevant","reason":"The ad uses a fake TV-news scandal about a public figure and a microphone/live-broadcast hook on a throwaway domain, which is a hidden-offer finance-scam prelander pattern.","advertiser":"24 news","product":"Fake-news finance prelander","category":"other_relevant","grey_signals":["fake-news style","public-figure bait","fake video creative","throwaway domain"],"language":"Turkish"}}
{{"result":"relevant","reason":"The ad uses Czech fake-news/public-figure bait about leaked truth, arrest or prison consequences, and a random lead-gen domain, matching a hidden finance-scam prelander.","advertiser":"Hotnews","product":"Fake-news finance prelander","category":"other_relevant","grey_signals":["fake-news style","public-figure bait","sensational scandal","throwaway domain"],"language":"Czech"}}
{{"result":"relevant","reason":"The ad promises monthly income from a vague crypto system on a throwaway domain.","advertiser":"Crypto Income 24","product":"Crypto income funnel","category":"crypto","grey_signals":["monthly income claim","vague offer","throwaway domain"],"language":"English"}}
{{"result":"relevant","reason":"The ad uses a Philippine public/business figure and Caticlan City app branding with a click-below CTA and mismatched lead-gen domain, matching a hidden finance-scam prelander pattern.","advertiser":"Philippine Update","product":"Fake government-app finance prelander","category":"other_relevant","grey_signals":["public-figure bait","government-app impersonation","registration CTA","mismatched domain"],"language":"English"}}
{{"result":"relevant","reason":"The ad uses a fake GMA/Fast Talk scandal with a Philippine governor or central-bank figure and a staged emergency on a throwaway domain, matching a hidden finance-scam prelander pattern.","advertiser":"Live TV Philippines","product":"Fake-TV finance prelander","category":"other_relevant","grey_signals":["fake-TV style","official/public-figure bait","sensational scandal","throwaway domain"],"language":"English"}}
{{"result":"not_relevant","reason":"The ad is for a normal forex broker and does not show scam, impersonation, fake-news, or exaggerated profit-funnel signals."}}
{{"result":"not_relevant","reason":"The ad is for a legitimate crypto exchange brand without grey/scam buyer-funnel signals."}}
{{"result":"not_relevant","reason":"The ad is a normal political news post from a consistent publisher/domain and does not show a suspicious redirect, throwaway lead-gen funnel, or hidden finance-scam prelander pattern."}}
{{"result":"not_relevant","reason":"The ad is an ordinary street-interview or emotional TV/person video with generic 'method', 'easy start', or registration wording; random domains and Facebook tracking alone are not enough without finance, bank/state, public-figure, or fake-news scandal evidence."}}
{{"result":"not_relevant","reason":"The ad is a prop trading funded-account discount/BOGO promotion, not a deceptive public-figure, fake-news, Telegram-signal, or guaranteed-profit scam funnel."}}
{{"result":"not_relevant","reason":"The ad is a normal branded stock-picking or portfolio research app and does not use fake-news impersonation, Telegram/signal lead-gen, or throwaway scam prelander tactics."}}
{{"result":"not_relevant","reason":"The ad is a generic AI webinar promising monthly income, but it is not specifically finance, crypto, forex, trading, yield, signal, broker-deposit, copy-trading, or fake-news finance-prelander related."}}
{{"result":"not_relevant","reason":"The ad is a generic make-money-online guide without a specific finance, crypto, forex, trading, yield, signal, broker-deposit, copy-trading, or fake-news finance-prelander hook."}}
{{"result":"not_relevant","reason":"The ad is for employee benefits/payment cards, not a grey consumer trading or investment funnel."}}
{{"result":"not_relevant","reason":"The ad is a Microsoft cloud-partner skilling campaign, not a grey finance or investment funnel."}}
{{"result":"not_relevant","reason":"The ad sells in-game currency or virtual items; gaming balance, bonds, and refunds are not finance-scam evidence."}}
{{"result":"not_relevant","reason":"The payment-app ad uses a standard mobile attribution deep link, which is not evidence of impersonation."}}
{{"result":"not_relevant","reason":"The ad is for a hotel booking offer, unrelated to finance, crypto, trading, or investment scams."}}
{{"result":"not_relevant","reason":"The ad is a gambling/casino/betting funnel without crypto, trading, yield, or investment messaging."}}
{{"result":"not_relevant","reason":"The ad is a deceptive health/nutra advertorial with hospital or news impersonation, but it does not reveal a finance, crypto, trading, or investment offer."}}
{{"result":"not_relevant","reason":"The ad is for a consistently branded forex education course and only promises learning or financial freedom, without fake-news bait, impersonation, guaranteed returns, or another scam-funnel signal."}}
"""

VISION_PROMPT = f"""\
Analyze this Facebook ad screenshot together with the metadata below.

{_TEXT_SCOPE}

{_RESPONSE_FORMAT}

Pay attention to visual signs such as fake-news layouts, public figures, suspicious bank/state/brand impersonation, trading charts, crypto symbols, profit claims, celebrity/deepfake-style investment pitches, app dashboards for deposits/returns, and suspicious "earn money" promises.
Also watch for hidden-offer prelander visuals: fake TV-news screenshots, red breaking-news banners, fake play buttons, Turkish/Czech subtitles, politicians/ministers/presidents/TV presenters, parliament scenes, police/arrest/prison scenes, bank branches/ATMs/cash, and random-domain "learn more/register" Facebook cards.
For Philippine traffic, watch for fake GMA Network/Fast Talk/news-show scandals, governors/mayors/BSP or central-bank officials, TV hosts and business leaders, staged emergencies, and fake local-government/Caticlan City app endorsements with click/register CTAs on mismatched domains. These are hidden finance-prelander evidence only when combined with performance-funnel signals. Health/nutra, gambling, dating, and e-commerce remain out of scope even when deceptive unless a finance/investment offer is also evidenced.
"""

PREFILTER_TEXT_PROMPT = f"""\
Pre-screen this Facebook ad using only metadata and text visible in the
Facebook card. This decision controls whether an authenticated Facebook
profile is allowed to interact with the ad.

{_TEXT_SCOPE}

{_PREFILTER_RESPONSE_FORMAT}
"""

PREFILTER_VISION_PROMPT = f"""\
Pre-screen this Facebook ad using only the Facebook feed-card screenshot and
its metadata. This decision controls whether an authenticated Facebook
profile is allowed to play the ad video or click its CTA.

{_TEXT_SCOPE}

{_PREFILTER_RESPONSE_FORMAT}
"""


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    relevant: bool
    summary: dict[str, Any]
    raw_response: str | None = None
    source: str = "disabled"


def parse_model_json(
    text: str,
    *,
    allowed_results: set[str] | None = None,
) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"result": "not_relevant", "reason": text[:240] or "Invalid model JSON"}
    accepted = allowed_results or {"relevant", "not_relevant"}
    result = str(data.get("result") or "not_relevant").lower()
    if result not in accepted:
        result = "not_relevant"
    data["result"] = result
    if not data.get("reason"):
        data["reason"] = "No reason provided."
    return data


def _contains_term(text: str, term: str) -> bool:
    """Match words/phrases without treating fragments inside other words as hits."""
    candidate = term.strip().casefold()
    if not candidate:
        return False
    if candidate in {"$", "₺"}:
        return candidate in text

    prefix = candidate.endswith("*")
    if prefix:
        candidate = candidate[:-1]
    words = re.findall(r"\w+", candidate, flags=re.UNICODE)
    if not words:
        return candidate in text.casefold()

    pattern = r"(?<!\w)" + r"[\W_]+".join(re.escape(word) for word in words)
    if not prefix:
        pattern += r"(?!\w)"
    return re.search(pattern, text.casefold(), flags=re.UNICODE) is not None


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _has_percentage_bonus(text: str) -> bool:
    return re.search(
        r"(?<!\w)\d{1,3}\s*%\s*(?:extra|bonus|bono)(?!\w)",
        text.casefold(),
        flags=re.UNICODE,
    ) is not None


def _rejected(reason: str) -> dict[str, Any]:
    # Do not leave category/grey_signals from a positive model result on a
    # deterministic rejection; that produced internally contradictory output.
    return {"result": "not_relevant", "reason": reason}


def _hostname(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate if "://" in candidate else f"//{candidate}")
    return (parsed.hostname or "").casefold().removeprefix("www.")


def _advertiser_matches_domain(advertiser: Any, domain: Any) -> bool:
    host = _hostname(domain)
    if not host:
        return False
    advertiser_tokens = re.findall(
        r"[\w]+",
        str(advertiser or "").casefold(),
        flags=re.UNICODE,
    )
    advertiser_compact = "".join(advertiser_tokens)
    labels = [
        "".join(re.findall(r"[\w]+", label, flags=re.UNICODE))
        for label in host.split(".")[:-1]
    ]
    generic_labels = {
        "www",
        "lp",
        "go",
        "app",
        "apps",
        "ad",
        "ads",
        "link",
        "links",
        "landing",
        "try",
        "get",
        "m",
    }
    brand_labels = [
        label
        for label in labels
        if len(label) >= 4 and label not in generic_labels
    ]
    if any(
        label in advertiser_compact or advertiser_compact in label
        for label in brand_labels
        if advertiser_compact
    ):
        return True
    if any(
        token == label
        for token in advertiser_tokens
        for label in brand_labels
        if len(token) >= 4
    ):
        return True
    host_compact = "".join(
        re.findall(r"[\w]+", host, flags=re.UNICODE)
    )
    token_matches = [
        token
        for token in advertiser_tokens
        if len(token) >= 2 and token in host_compact
    ]
    return len(token_matches) >= 2 and any(
        len(token) >= 4 for token in token_matches
    )


def _is_mobile_attribution_host(host: str) -> bool:
    return any(
        host == known_host or host.endswith(f".{known_host}")
        for known_host in _MOBILE_ATTRIBUTION_HOSTS
    )


def apply_scope_guards(raw: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic exclusions where the model is often too permissive."""
    if data.get("result") != "relevant":
        return data

    raw_text_parts: list[str] = []
    for value in (
        raw.get("advertiser"),
        raw.get("displayed_domain"),
        raw.get("headline"),
        raw.get("ad_text"),
        raw.get("cta"),
        raw.get("cta_href"),
        raw.get("landing_full"),
        raw.get("landing_clean"),
    ):
        if value:
            raw_text_parts.append(str(value))

    model_text_parts: list[str] = []
    for value in (
        data.get("reason"),
        data.get("product"),
        data.get("category"),
    ):
        if value:
            model_text_parts.append(str(value))
    grey_signals = data.get("grey_signals")
    if isinstance(grey_signals, list):
        model_text_parts.extend(str(item) for item in grey_signals if item)

    raw_text = " ".join(raw_text_parts).casefold()
    model_text = " ".join(model_text_parts).casefold()
    text = " ".join((raw_text, model_text))
    category = str(data.get("category") or "").strip().casefold()
    displayed_host = _hostname(
        raw.get("displayed_domain")
        or raw.get("landing_clean")
        or raw.get("landing_full")
    )
    has_gambling_signal = (
        _contains_any_term(text, _GAMBLING_TERMS)
        or _contains_any_term(text, _GAMBLING_ACQUISITION_TERMS)
        or _has_percentage_bonus(text)
        or any(marker in displayed_host for marker in _GAMBLING_HOST_MARKERS)
    )
    raw_has_hard_finance_signal = _contains_any_term(raw_text, _HARD_FINANCE_TERMS)
    model_has_hard_finance_signal = _contains_any_term(
        model_text,
        _HARD_FINANCE_TERMS,
    )
    raw_has_fake_news_finance_prelander = _contains_any_term(
        raw_text,
        _FAKE_NEWS_FINANCE_PRELANDER_TERMS,
    )
    raw_has_scam_evidence = _contains_any_term(
        raw_text,
        _RAW_SCAM_EVIDENCE_TERMS,
    )
    raw_has_generic_ai_income = _contains_any_term(
        raw_text, _GENERIC_AI_TERMS
    ) and _contains_any_term(raw_text, _GENERIC_INCOME_TERMS)
    has_supporting_only_funnel_signal = _contains_any_term(
        text,
        _SUPPORTING_ONLY_FUNNEL_TERMS,
    )
    has_strong_target_anchor = _contains_any_term(text, _STRONG_TARGET_ANCHOR_TERMS)
    if category and category not in _ALLOWED_RELEVANT_CATEGORIES:
        return _rejected(
            "Out-of-scope category: only grey finance, crypto, forex, trading, "
            "investment, yield, broker, money-system, or hidden finance "
            "prelander funnels are relevant."
        )
    if (
        _contains_any_term(text, _HEALTH_PRODUCT_TERMS)
        and not raw_has_hard_finance_signal
    ):
        return _rejected(
            "Health/nutra/medical product funnel without an evidenced finance, "
            "crypto, trading, yield, or investment offer."
        )
    if (
        _contains_any_term(text, _ENTERPRISE_TECH_TERMS)
        and not raw_has_hard_finance_signal
        and not raw_has_fake_news_finance_prelander
    ):
        return _rejected(
            "Corporate technology, cloud-partner, or professional-skilling "
            "campaign without a finance-scam offer."
        )
    if (
        _contains_any_term(text, _GAMING_TERMS)
        and not raw_has_hard_finance_signal
    ):
        return _rejected(
            "Gaming product, virtual item, or in-game currency offer without "
            "a real finance, trading, crypto, or investment funnel."
        )
    if (
        _is_mobile_attribution_host(displayed_host)
        and not raw_has_hard_finance_signal
        and not raw_has_fake_news_finance_prelander
    ):
        return _rejected(
            "Known mobile attribution/deep-link host is not evidence of brand "
            "impersonation or a grey finance funnel."
        )
    if _contains_any_term(text, _FINANCE_EDUCATION_TERMS) and not _contains_any_term(
        text,
        _STRONG_SCAM_EVIDENCE_TERMS,
    ):
        return _rejected(
            "Ordinary branded finance/trading education without fake-news, "
            "impersonation, guaranteed returns, or another strong scam-funnel signal."
        )
    if (
        (
            raw_has_hard_finance_signal
            or model_has_hard_finance_signal
            or category in {"crypto", "forex", "trading", "broker", "investing", "yield"}
        )
        and _advertiser_matches_domain(
            raw.get("advertiser"),
            raw.get("displayed_domain") or raw.get("landing_clean"),
        )
        and not raw_has_fake_news_finance_prelander
        and not raw_has_scam_evidence
    ):
        return _rejected(
            "Consistently branded broker, prop-firm, or trading-service "
            "promotion without fake-news impersonation, a hidden prelander, "
            "or a guaranteed-return scam claim."
        )
    if (
        has_gambling_signal
        and not raw_has_hard_finance_signal
        and not raw_has_fake_news_finance_prelander
    ):
        return _rejected(
            "Pure casino/gambling/betting offer without a hard crypto, forex, "
            "trading, or yield scam signal."
        )
    if (
        raw_has_generic_ai_income
        and not raw_has_hard_finance_signal
        and not raw_has_fake_news_finance_prelander
        and not has_strong_target_anchor
    ):
        return _rejected(
            "Generic AI/webinar/online-income offer without a hard finance, "
            "crypto, forex, trading, signal, broker-deposit, or fake-news "
            "finance-prelander signal in the ad itself."
        )
    if has_supporting_only_funnel_signal and not has_strong_target_anchor:
        return _rejected(
            "Generic redirect/tracking/register-style funnel without a strong "
            "finance, bank/state, public-figure, fake-news scandal, or "
            "investment-scam anchor."
        )
    return data


def apply_prefilter_uncertainty_guard(
    raw: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Keep visually incomplete link cards out of the definitive deny bucket.

    Facebook occasionally renders only an advertiser avatar and a destination
    domain while the actual creative is still lazy or unavailable. Historical
    runs contain confirmed hidden-offer ads in exactly this shape. Treating the
    empty card as ordinary content loses those ads; allowing it would let an
    authenticated profile click an unclassified destination. ``uncertain`` is
    the safe middle state and can be resolved without profile cookies.
    """
    if data.get("result") != "not_relevant":
        return data
    if str(raw.get("ad_type") or "").casefold() != "link":
        return data

    displayed_domain = _hostname(raw.get("displayed_domain"))
    if not displayed_domain:
        return data
    headline = str(raw.get("headline") or "").strip().casefold()
    normalized_headline = _hostname(headline)
    domain_only_headline = not headline or normalized_headline == displayed_domain
    missing_copy = not str(raw.get("ad_text") or "").strip()
    missing_cta = not str(raw.get("cta") or "").strip()
    creative = str(raw.get("creative_img") or "")
    avatar_only = (
        not creative
        or bool(re.search(r"/v/t\d+\.\d+-1/", creative))
        or bool(re.search(r"(?:^|[_=&])p(?:135|160|180|240)x(?:135|160|180|240)", creative))
    )
    screenshot_issue = str(raw.get("screenshot_issue") or "").casefold()
    visibly_incomplete = screenshot_issue in {
        "blank_media",
        "viewport_fallback",
    } or avatar_only
    has_recovery_handle = bool(
        str(raw.get("cta_href") or "").strip()
        or str(raw.get("facebook_post_url") or "").strip()
    )
    if not (
        domain_only_headline
        and missing_copy
        and missing_cta
        and visibly_incomplete
        and has_recovery_handle
    ):
        return data

    guarded = dict(data)
    guarded["result"] = "uncertain"
    guarded["reason"] = (
        "The Facebook link card is visually incomplete and contains only an "
        "advertiser/domain shell; resolve its passive CTA URL in an isolated "
        "cookie-free browser before making a final decision."
    )
    guarded["prefilter_original_result"] = "not_relevant"
    if data.get("reason"):
        guarded["prefilter_original_reason"] = str(data["reason"])
    return guarded


class FacebookAdRelevanceFilter:
    def __init__(
        self,
        gemini: GeminiClient | None,
        *,
        enabled: bool,
        concurrency: int = 3,
    ) -> None:
        self._gemini = gemini
        self.enabled = enabled and gemini is not None
        self._concurrency = max(1, concurrency)

    @classmethod
    def from_config(cls, config: Config) -> FacebookAdRelevanceFilter:
        enabled = config.facebook.relevance_filter_enabled
        if not enabled or not config.gemini.api_key:
            return cls(None, enabled=False)
        return cls(
            GeminiClient(config.gemini.api_key, config.gemini.model),
            enabled=True,
            concurrency=config.facebook.relevance_filter_concurrency,
        )

    async def filter_raw_ads(
        self,
        raw_ads: list[dict[str, Any]],
        run_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.enabled:
            return raw_ads, []

        semaphore = asyncio.Semaphore(self._concurrency)

        async def analyze_one(
            index: int, raw: dict[str, Any]
        ) -> tuple[int, dict[str, Any], RelevanceResult]:
            async with semaphore:
                result = await self.analyze_raw_ad(raw, run_dir)
                return index, raw, result

        tasks = [analyze_one(index, raw) for index, raw in enumerate(raw_ads, start=1)]
        results = await asyncio.gather(*tasks)

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for index, raw, result in sorted(results, key=lambda item: item[0]):
            decorated = dict(raw)
            decorated["relevance"] = result.summary
            decorated["relevance_source"] = result.source
            if result.relevant:
                accepted.append(decorated)
            else:
                rejected.append(decorated)
                logger.info(
                    "FB relevance rejected idx=%s advertiser=%r domain=%r reason=%s",
                    index,
                    raw.get("advertiser"),
                    raw.get("displayed_domain"),
                    result.summary.get("reason"),
                )
        return accepted, rejected

    async def analyze_raw_ad(
        self,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        prefilter: bool = False,
    ) -> RelevanceResult:
        if not self.enabled or self._gemini is None:
            return RelevanceResult(
                True, {"result": "relevant", "reason": "filter disabled"}
            )

        allowed_results = (
            {"relevant", "not_relevant", "uncertain"}
            if prefilter
            else {"relevant", "not_relevant"}
        )
        metadata_prompt = self._build_prompt(
            raw,
            vision=False,
            prefilter=prefilter,
        )
        video_path = self._first_existing_path(run_dir, raw, ("video", "video_path"))
        if video_path is not None and video_path.stat().st_size <= 20 * 1024 * 1024:
            try:
                raw_response = await self._gemini.generate_from_video(
                    video_path,
                    self._build_prompt(raw, vision=True, prefilter=prefilter),
                )
                data = parse_model_json(
                    raw_response,
                    allowed_results=allowed_results,
                )
                data = apply_scope_guards(raw, data)
                if prefilter:
                    data = apply_prefilter_uncertainty_guard(raw, data)
                if data["result"] == "relevant":
                    return RelevanceResult(True, data, raw_response, "video")
            except Exception as exc:
                logger.warning(
                    "FB relevance video analysis failed for %s: %s", video_path, exc
                )

        image_result: RelevanceResult | None = None
        image_paths = self._existing_paths(
            run_dir,
            raw,
            ("screenshot", "landing_screenshot"),
        )
        if len(image_paths) > 1:
            try:
                raw_response = await self._gemini.generate_from_images(
                    [path for _, path in image_paths],
                    self._build_prompt(
                        raw,
                        vision=True,
                        image_source="combined_screenshots",
                        prefilter=prefilter,
                    ),
                )
                data = parse_model_json(
                    raw_response,
                    allowed_results=allowed_results,
                )
                data = apply_scope_guards(raw, data)
                if prefilter:
                    data = apply_prefilter_uncertainty_guard(raw, data)
                return RelevanceResult(
                    data["result"] == "relevant",
                    data,
                    raw_response,
                    "combined_screenshots",
                )
            except Exception as exc:
                logger.warning(
                    "FB relevance combined image analysis failed for %s: %s",
                    [path for _, path in image_paths],
                    exc,
                )

        for image_source, image_path in image_paths:
            try:
                raw_response = await self._gemini.generate_from_image(
                    image_path,
                    self._build_prompt(
                        raw,
                        vision=True,
                        image_source=image_source,
                        prefilter=prefilter,
                    ),
                )
                data = parse_model_json(
                    raw_response,
                    allowed_results=allowed_results,
                )
                data = apply_scope_guards(raw, data)
                if prefilter:
                    data = apply_prefilter_uncertainty_guard(raw, data)
                result = RelevanceResult(
                    data["result"] == "relevant",
                    data,
                    raw_response,
                    image_source,
                )
                if result.relevant:
                    return result
                image_result = result
            except Exception as exc:
                logger.warning(
                    "FB relevance image analysis failed for %s: %s", image_path, exc
                )

        if image_result is not None:
            return image_result

        raw_response = await self._gemini.generate_from_text(metadata_prompt)
        data = parse_model_json(
            raw_response,
            allowed_results=allowed_results,
        )
        data = apply_scope_guards(raw, data)
        if prefilter:
            data = apply_prefilter_uncertainty_guard(raw, data)
        return RelevanceResult(
            data["result"] == "relevant",
            data,
            raw_response,
            "metadata",
        )

    def _build_prompt(
        self,
        raw: dict[str, Any],
        *,
        vision: bool,
        image_source: str | None = None,
        prefilter: bool = False,
    ) -> str:
        fields = {
            "advertiser": raw.get("advertiser"),
            "ad_type": raw.get("ad_type"),
            "has_video": raw.get("has_video"),
            "displayed_domain": raw.get("displayed_domain"),
            "headline": raw.get("headline"),
            "ad_text": raw.get("ad_text"),
            "cta": raw.get("cta"),
            "cta_href": raw.get("cta_href"),
            "landing_full": raw.get("landing_full"),
            "landing_clean": raw.get("landing_clean"),
            "fb_ad_id": raw.get("fb_ad_id"),
            "utm": raw.get("utm"),
        }
        lines = []
        for key, value in fields.items():
            if value in (None, "", {}):
                continue
            if isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"{key}: {value}")
        if prefilter:
            base = PREFILTER_VISION_PROMPT if vision else PREFILTER_TEXT_PROMPT
        else:
            base = VISION_PROMPT if vision else TEXT_PROMPT
        source_context = ""
        if image_source == "screenshot":
            source_context = "\n\nImage source: Facebook feed ad card."
        elif image_source == "landing_screenshot":
            source_context = (
                "\n\nImage source: landing page captured after clicking the ad. "
                "Treat deceptive content visible only on this landing page as "
                "evidence for the same ad."
            )
        elif image_source == "combined_screenshots":
            source_context = (
                "\n\nImage sources: Image 1 is the Facebook feed ad card; Image 2 "
                "is the landing page captured after clicking that ad. Classify "
                "the complete funnel. Deceptive evidence in either image is "
                "sufficient, and a blank/loading image must not override "
                "evidence visible in the other image."
            )
        return f"{base}{source_context}\n\nAd metadata:\n" + "\n".join(lines)

    @staticmethod
    def _first_existing_path(
        run_dir: Path,
        raw: dict[str, Any],
        keys: tuple[str, ...],
    ) -> Path | None:
        for key in keys:
            value = raw.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            path = Path(value)
            if not path.is_absolute():
                path = run_dir / path
            if path.exists():
                return path
        return None

    @staticmethod
    def _existing_paths(
        run_dir: Path,
        raw: dict[str, Any],
        keys: tuple[str, ...],
    ) -> list[tuple[str, Path]]:
        paths: list[tuple[str, Path]] = []
        seen: set[Path] = set()
        for key in keys:
            value = raw.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            path = Path(value)
            if not path.is_absolute():
                path = run_dir / path
            path = path.resolve()
            if path.exists() and path not in seen:
                paths.append((key, path))
                seen.add(path)
        return paths
