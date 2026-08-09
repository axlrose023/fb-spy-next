from __future__ import annotations

import json
from typing import Any

from .prompt_examples import EXAMPLES
from .scope_prompt import TEXT_SCOPE

RESPONSE_FORMAT = """\
Respond with ONLY a JSON object.

If relevant:
{"result":"relevant","reason":"one sentence","advertiser":"name","product":"short product","category":"crypto|forex|trading|broker|investing|yield|make_money|other_relevant","grey_signals":["short evidence"],"language":"detected language"}

If not relevant:
{"result":"not_relevant","reason":"one sentence"}

If there is not enough evidence:
{"result":"not_relevant","reason":"Insufficient evidence of a grey finance, crypto, trading, or investment-scam offer."}
"""

PREFILTER_RESPONSE_FORMAT = """\
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

{TEXT_SCOPE}

{RESPONSE_FORMAT}

{EXAMPLES}"""

VISION_PROMPT = f"""\
Analyze this Facebook ad screenshot together with the metadata below.

{TEXT_SCOPE}

{RESPONSE_FORMAT}

Pay attention to visual signs such as fake-news layouts, public figures, suspicious bank/state/brand impersonation, trading charts, crypto symbols, profit claims, celebrity/deepfake-style investment pitches, app dashboards for deposits/returns, and suspicious "earn money" promises.
Also watch for hidden-offer prelander visuals: fake TV-news screenshots, red breaking-news banners, fake play buttons, Turkish/Czech subtitles, politicians/ministers/presidents/TV presenters, parliament scenes, police/arrest/prison scenes, bank branches/ATMs/cash, and random-domain "learn more/register" Facebook cards.
For Philippine traffic, watch for fake GMA Network/Fast Talk/news-show scandals, governors/mayors/BSP or central-bank officials, TV hosts and business leaders, staged emergencies, and fake local-government/Caticlan City app endorsements with click/register CTAs on mismatched domains. These are hidden finance-prelander evidence only when combined with performance-funnel signals. Health/nutra, gambling, dating, and e-commerce remain out of scope even when deceptive unless a finance/investment offer is also evidenced.
"""

PREFILTER_TEXT_PROMPT = f"""\
Pre-screen this Facebook ad using only metadata and text visible in the
Facebook card. This decision controls whether an authenticated Facebook
profile is allowed to interact with the ad.

{TEXT_SCOPE}

{PREFILTER_RESPONSE_FORMAT}
"""

PREFILTER_VISION_PROMPT = f"""\
Pre-screen this Facebook ad using only the Facebook feed-card screenshot and
its metadata. This decision controls whether an authenticated Facebook
profile is allowed to play the ad video or click its CTA.

{TEXT_SCOPE}

{PREFILTER_RESPONSE_FORMAT}
"""

_PROMPT_FIELDS = (
    "advertiser",
    "ad_type",
    "has_video",
    "displayed_domain",
    "headline",
    "ad_text",
    "cta",
    "cta_href",
    "landing_full",
    "landing_clean",
    "fb_ad_id",
    "utm",
)


def build_prompt(
    raw: dict[str, Any],
    *,
    vision: bool,
    image_source: str | None = None,
    prefilter: bool = False,
) -> str:
    lines: list[str] = []
    for key in _PROMPT_FIELDS:
        value = raw.get(key)
        if value in (None, "", {}):
            continue
        if isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {value}")
    if prefilter:
        base = PREFILTER_VISION_PROMPT if vision else PREFILTER_TEXT_PROMPT
    else:
        base = VISION_PROMPT if vision else TEXT_PROMPT
    source_context = _source_context(image_source)
    return f"{base}{source_context}\n\nAd metadata:\n" + "\n".join(lines)


def _source_context(image_source: str | None) -> str:
    if image_source == "screenshot":
        return "\n\nImage source: Facebook feed ad card."
    if image_source == "landing_screenshot":
        return (
            "\n\nImage source: landing page captured after clicking the ad. "
            "Treat deceptive content visible only on this landing page as "
            "evidence for the same ad."
        )
    if image_source == "combined_screenshots":
        return (
            "\n\nImage sources: Image 1 is the Facebook feed ad card; Image 2 "
            "is the landing page captured after clicking that ad. Classify "
            "the complete funnel. Deceptive evidence in either image is "
            "sufficient, and a blank/loading image must not override "
            "evidence visible in the other image."
        )
    return ""
