import json
from pathlib import Path

import pytest

from app.services.facebook.relevance import (
    TEXT_PROMPT,
    VISION_PROMPT,
    FacebookAdRelevanceFilter,
    _contains_term,
    apply_scope_guards,
)


def test_facebook_relevance_prompt_is_not_general_finance_classifier() -> None:
    prompt = TEXT_PROMPT.casefold()

    assert "not a general finance" in prompt
    assert "target classes" in prompt
    assert "clear grey/scam" in prompt
    assert "normal forex broker" in prompt
    assert "legitimate crypto exchange" in prompt
    assert "casino winnings" in prompt
    assert "betting payouts" in prompt


def test_facebook_relevance_prompt_rejects_non_finance_verticals() -> None:
    prompt = TEXT_PROMPT.casefold()

    assert "health/nutra/medical products and funnels" in prompt
    assert "fake medical advertorials" in prompt
    assert "pure casino/gambling/sports betting" in prompt
    assert "dating/chat acquisition" in prompt
    assert "generic e-commerce, turnkey-business" in prompt
    assert "ordinary branded forex/trading education" in prompt
    assert "reject it even when it is deceptive" in prompt


def test_facebook_relevance_prompt_keeps_fake_news_finance_prelanders() -> None:
    prompt = TEXT_PROMPT.casefold()

    assert "hidden-offer fake-news prelander" in prompt
    assert "first facebook card does not visibly mention crypto" in prompt
    assert "public funds" in prompt
    assert "finance minister" in prompt
    assert "throwaway tracking domain" in prompt
    assert "fake-news finance prelander" in prompt
    assert "microphone left on" in prompt
    assert "truth revealed" in prompt
    assert "country shocked" in prompt
    assert "affiliate/autologin" in prompt
    assert "facebook campaign parameters" in prompt
    assert "ad_id/pixel/token parameters" in prompt
    assert 'turkish "kayit" ads' in prompt
    assert "czech fake čt/news-style ads" in prompt
    assert "generalize from philippine examples" in prompt
    assert "gma network/fast talk" in prompt
    assert "caticlan/local-government app" in prompt
    assert "ordinary person talking in a video" in prompt
    assert "supporting signals, not the target class" in prompt


def test_facebook_relevance_prompt_rejects_broad_finance_and_generic_make_money() -> (
    None
):
    prompt = TEXT_PROMPT.casefold()

    assert "normal political/news/media ads" in prompt
    assert "consistent publishers" in prompt
    assert "hidden finance-scam prelander pattern" in prompt
    assert (
        "ordinary ugc, street-interview, selfie, lifestyle, emotional tv clips"
        in prompt
    )
    assert 'generic "method/easy start/three months/register now" ads' in prompt
    assert "ordinary street-interview or emotional tv/person video" in prompt
    assert "random domains and facebook tracking alone are not enough" in prompt
    assert "prop/funded account challenge promos" in prompt
    assert "bogo offers" in prompt
    assert "demo-account reward ads" in prompt
    assert "stock-picking apps" in prompt
    assert "normal broker commodity/gold/forex ads" in prompt
    assert "generic ai/business/webinar/make-money-online courses" in prompt
    assert "generic make-money clarification" in prompt
    assert "generic ai, entrepreneurship, webinar, or online-income offer" in prompt
    assert "even if it promises a large monthly income" in prompt
    assert "prop trading funded-account discount/bogo promotion" in prompt
    assert "normal branded stock-picking or portfolio research app" in prompt
    assert "generic ai webinar promising monthly income" in prompt


def test_facebook_vision_prompt_mentions_scam_buyer_funnel_signals() -> None:
    prompt = VISION_PROMPT.casefold()

    assert "fake-news layouts" in prompt
    assert "public figures" in prompt
    assert "brand impersonation" in prompt
    assert "earn money" in prompt
    assert "fake tv-news screenshots" in prompt
    assert "fake play buttons" in prompt
    assert "turkish/czech subtitles" in prompt
    assert "police/arrest/prison scenes" in prompt
    assert "fake gma network/fast talk/news-show scandals" in prompt
    assert "caticlan city app endorsements" in prompt
    assert (
        "health/nutra, gambling, dating, and e-commerce remain out of scope" in prompt
    )


def test_term_matching_does_not_match_fragments_inside_words() -> None:
    assert not _contains_term("utm_medium=paid", "ai")
    assert not _contains_term("Learn more", "earn")
    assert not _contains_term("a better offer", "bet")
    assert _contains_term("AI-powered income", "ai")
    assert _contains_term("Start to earn today", "earn")


class _ImageSequenceGemini:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.image_calls: list[tuple[Path, str]] = []
        self.multi_image_calls: list[tuple[list[Path], str]] = []

    async def generate_from_image(self, path: Path, prompt: str) -> str:
        self.image_calls.append((path, prompt))
        return json.dumps(self.responses.pop(0))

    async def generate_from_images(self, paths: list[Path], prompt: str) -> str:
        self.multi_image_calls.append((paths, prompt))
        return json.dumps(self.responses.pop(0))

    async def generate_from_text(self, prompt: str) -> str:
        raise AssertionError(
            "metadata fallback should not run when images were analyzed"
        )

    async def generate_from_video(self, path: Path, prompt: str) -> str:
        raise AssertionError("video analysis is not expected in this test")


@pytest.mark.asyncio
async def test_filter_analyzes_ad_and_landing_together(
    tmp_path: Path,
) -> None:
    ad_screenshot = tmp_path / "ad.png"
    landing_screenshot = tmp_path / "landing.png"
    ad_screenshot.touch()
    landing_screenshot.touch()
    gemini = _ImageSequenceGemini(
        [
            {
                "result": "relevant",
                "reason": (
                    "The landing is a fake GMA scandal with a Philippine "
                    "governor on a throwaway registration domain."
                ),
                "category": "other_relevant",
                "grey_signals": [
                    "fake-TV style",
                    "public-figure bait",
                    "registration funnel",
                ],
            },
        ]
    )
    relevance_filter = FacebookAdRelevanceFilter(gemini, enabled=True)

    result = await relevance_filter.analyze_raw_ad(
        {
            "advertiser": "Generic profile",
            "screenshot": ad_screenshot.name,
            "landing_screenshot": landing_screenshot.name,
        },
        tmp_path,
    )

    assert result.relevant is True
    assert result.source == "combined_screenshots"
    assert gemini.image_calls == []
    assert len(gemini.multi_image_calls) == 1
    paths, prompt = gemini.multi_image_calls[0]
    assert paths == [ad_screenshot, landing_screenshot]
    assert "Image 1 is the Facebook feed ad card" in prompt
    assert "blank/loading image must not override" in prompt


def test_scope_guard_rejects_pure_gambling_bonus() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "NaneMedya",
            "displayed_domain": "texbet.com",
            "headline": "Dene, Sende Kazan!",
        },
        {
            "result": "relevant",
            "reason": "The ad promises a casino bonus and instant winnings with clear grey/scam signals.",
            "category": "make_money",
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_coinbet_hostname_mislabeled_as_crypto() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Gabriela redfire",
            "displayed_domain": "coinbetlanding1.vercel.app",
            "headline": "ENTRÁ S1N DEM0R4S",
            "ad_text": "Acceso ráp1do + 100% extr4",
            "cta": "Registrarte",
        },
        {
            "result": "relevant",
            "reason": (
                "The ad uses a suspicious coinbet domain and bonus to push "
                "users into a crypto registration funnel."
            ),
            "product": "Crypto/investment lead-gen funnel",
            "category": "crypto",
            "grey_signals": [
                "suspicious domain",
                "high bonus claim",
                "registration funnel",
            ],
        },
    )

    assert data["result"] == "not_relevant"
    assert "casino/gambling/betting" in data["reason"]


@pytest.mark.parametrize(
    ("raw", "model"),
    [
        (
            {
                "advertiser": "Golden Para Todos",
                "displayed_domain": "int.goldenparatodos.store",
                "headline": "CASELY - Fundas, cargadores y accesorios",
                "cta": "Contactarnos",
            },
            {
                "result": "relevant",
                "reason": (
                    "The creative offers 25% EXTRA in a luxurious setting and "
                    "redirects immediately to WhatsApp."
                ),
                "category": "make_money",
                "grey_signals": ["25% EXTRA", "WhatsApp redirect"],
            },
        ),
        (
            {
                "advertiser": "Lucky Rabbit",
                "displayed_domain": "cajero2.registrogratis.online",
                "headline": "Todas las plataformas!",
            },
            {
                "result": "relevant",
                "reason": (
                    "Cajero Imperial promises extra money through a WhatsApp "
                    "platform group."
                ),
                "category": "make_money",
                "grey_signals": ["WhatsApp funnel", "100% secure"],
            },
        ),
        (
            {
                "advertiser": "Latino Para Todos",
                "displayed_domain": "convertixapp.com",
                "cta": "Contactarnos",
            },
            {
                "result": "relevant",
                "reason": (
                    "The Zeus creative promises 50% EXTRA and redirects to "
                    "WhatsApp."
                ),
                "category": "make_money",
                "grey_signals": ["50% EXTRA", "discount code"],
            },
        ),
    ],
)
def test_scope_guard_rejects_argentina_casino_acquisition(
    raw: dict,
    model: dict,
) -> None:
    data = apply_scope_guards(raw, model)

    assert data["result"] == "not_relevant"
    assert "casino/gambling/betting" in data["reason"]


def test_scope_guard_keeps_crypto_trading_profit_claim() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Crypto Cash Daily",
            "displayed_domain": "one-trade-offer.vip",
            "headline": "Make $9,600 from one trade.",
        },
        {
            "result": "relevant",
            "reason": "The ad promises $9,600 from one trade in a crypto trading challenge.",
            "category": "trading",
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_does_not_treat_turkish_profit_word_as_gambling() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Kazanç Rotası",
            "displayed_domain": "sylji.website",
            "headline": "Koç hisseleri ile resmi fırsat",
        },
        {
            "result": "relevant",
            "reason": "The ad impersonates Koç Holding and promises high monthly returns from shares.",
            "category": "investing",
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_does_not_treat_generic_bonus_as_gambling() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Argentina Finance News",
            "displayed_domain": "throwaway.example",
            "headline": "Financial algorithm bonus report",
        },
        {
            "result": "relevant",
            "reason": "The ad uses fake news and public-figure bait.",
            "category": "investing",
            "grey_signals": ["fake-news style", "public-figure bait"],
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_rejects_generic_ai_income_without_finance_signal() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Batu Z",
            "displayed_domain": "aiscaleapp.com",
            "headline": "Bu akşam canlı webinar yapay zeka",
            "ad_text": "$10.000 kazanan girişimcilerin sistemi.",
            "cta": "Kaydol",
        },
        {
            "result": "relevant",
            "reason": "The ad promises $10,000 monthly through an AI system.",
            "category": "make_money",
        },
    )

    assert data["result"] == "not_relevant"
    assert set(data) == {"result", "reason"}


def test_scope_guard_keeps_canadian_fake_news_compensation_funnel() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Kyle Buchanan Sarah",
            "displayed_domain": "moderninsightreport.com",
            "headline": "Get Details",
            "cta": "Learn more",
            "landing_full": (
                "https://moderninsightreport.com/?utm_medium=paid"
                "&utm_source=fb&utm_campaign=launch"
            ),
        },
        {
            "result": "relevant",
            "reason": (
                "The ad impersonates a news broadcast and promises a "
                "guaranteed $50,000 compensation."
            ),
            "category": "make_money",
            "grey_signals": [
                "public-figure bait",
                "bank impersonation",
                "fake urgency",
                "advertiser mismatch",
            ],
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_keeps_philippine_government_app_finance_prelander() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Philippine Update",
            "displayed_domain": "random-app.example",
            "headline": "Click the link below",
            "cta": "Sign up",
            "landing_full": "https://random-app.example/?utm_source=fb",
        },
        {
            "result": "relevant",
            "reason": (
                "The ad uses a Philippine public/business figure and a fake "
                "Caticlan City government app endorsement."
            ),
            "category": "other_relevant",
            "grey_signals": [
                "public-figure bait",
                "government app impersonation",
                "registration funnel",
                "mismatched domain",
            ],
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_keeps_philippine_fake_tv_finance_prelander() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Live TV Philippines",
            "displayed_domain": "breaking-report.example",
            "headline": "Live TV sensation: the governor scandal",
            "cta": "Learn more",
            "landing_full": "https://breaking-report.example/?ad_id=123",
        },
        {
            "result": "relevant",
            "reason": (
                "A fake GMA Network Fast Talk scandal uses a governor and "
                "staged emergency as a hidden finance prelander."
            ),
            "category": "other_relevant",
            "grey_signals": [
                "fake-TV style",
                "official/public-figure bait",
                "throwaway domain",
            ],
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_rejects_deceptive_health_impersonation() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "National Kidney and Transplant Institute",
            "displayed_domain": "dohhospital.com",
            "headline": "Limited slots",
        },
        {
            "result": "relevant",
            "reason": "The ad impersonates a hospital to sell a kidney supplement.",
            "category": "nutra_health",
            "grey_signals": [
                "hospital impersonation",
                "fake medical advertorial",
                "limited slots",
                "mismatched domain",
            ],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_health_funnel_mislabeled_as_fake_news() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Brittany Kennedy",
            "displayed_domain": "sensesugar.com",
            "headline": "A simple morning ritual for brain support",
        },
        {
            "result": "relevant",
            "reason": (
                "A fake CBS News page uses Bill Gates to claim it reverses "
                "Alzheimer's and dementia."
            ),
            "product": "Brain supplement",
            "category": "other_relevant",
            "grey_signals": ["news impersonation", "miracle cure"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_normal_health_ad_without_deception() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "City Diagnostics",
            "displayed_domain": "citydiagnostics.example",
            "headline": "Annual blood test package",
        },
        {
            "result": "relevant",
            "reason": "The ad promotes a health service.",
            "category": "nutra_health",
            "grey_signals": [],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_microsoft_partner_skilling_campaign() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Microsoft AI Cloud Partner Program",
            "displayed_domain": "skilling-hub.com",
            "headline": "Turn ideas into market-ready solutions",
            "ad_text": "Develop new capabilities in Partner Skilling Hub.",
        },
        {
            "result": "relevant",
            "reason": "The campaign promises 5% more revenue per year.",
            "category": "make_money",
            "grey_signals": ["mismatched domain"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_consistently_branded_prop_firm() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Crypto Fund Trader",
            "displayed_domain": "cryptofundtrader.com",
            "headline": "Gold is live again",
            "ad_text": "Trade a funded account and withdraw your profits.",
        },
        {
            "result": "relevant",
            "reason": "The prop firm offers daily payouts and an 80% profit split.",
            "category": "trading",
            "grey_signals": ["daily payouts", "profit split"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_matches_brand_behind_generic_landing_subdomain() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Armadillo ES",
            "displayed_domain": "lp.armadillo.live",
            "headline": "Compite por premios reales",
            "ad_text": "Opera con capital real y compite por premios.",
        },
        {
            "result": "relevant",
            "reason": "The trading competition offers real capital and prizes.",
            "category": "trading",
            "grey_signals": ["cash prizes", "registration CTA"],
        },
    )

    assert data["result"] == "not_relevant"
    assert "Consistently branded" in data["reason"]


def test_scope_guard_rejects_branded_prop_firm_without_model_category() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Armadillo ES",
            "displayed_domain": "lp.armadillo.live",
            "headline": "Compite por premios reales",
            "ad_text": "Cada operación es una oportunidad para",
            "cta": "Más información",
        },
        {
            "result": "relevant",
            "reason": (
                "The ad promotes a funded trading system where the user "
                "operates and receives real earnings."
            ),
        },
    )

    assert data["result"] == "not_relevant"
    assert "Consistently branded" in data["reason"]


def test_scope_guard_rejects_branded_broker_giveaway() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Global PU Prime",
            "displayed_domain": "puprime.world",
            "headline": "Win a Signed Messi Jersey!",
            "ad_text": "Sign up and make a trade.",
        },
        {
            "result": "relevant",
            "reason": "A celebrity-related giveaway promotes a trading platform.",
            "category": "trading",
            "grey_signals": ["celebrity bait", "registration CTA"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_localized_broker_promo_on_brand_domain() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Global PU Prime",
            "displayed_domain": "webh5.pusglobal.app",
            "headline": "Opera en los mercados globales en vivo",
            "ad_text": "No te pierdas el último intento de Francia.",
        },
        {
            "result": "relevant",
            "reason": "A sports promotion leads to a branded trading platform.",
            "category": "trading",
            "grey_signals": ["sports promotion"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_in_game_bonds_offer() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Wings Store",
            "displayed_domain": "wngstore.com",
            "headline": "Arena Breakout World One",
        },
        {
            "result": "relevant",
            "reason": "The video game offer doubles an in-game bonds balance.",
            "category": "make_money",
            "grey_signals": ["100% refund"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_payment_app_attribution_link() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Mercado Pago",
            "displayed_domain": "852u.adj.st",
            "headline": "Mercado Pago",
            "cta": "Abrir app",
        },
        {
            "result": "relevant",
            "reason": "The attribution link is a suspicious mismatched domain.",
            "category": "other_relevant",
            "grey_signals": ["brand impersonation", "mismatched domain"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_branded_forex_education_without_scam_evidence() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "FTH Club",
            "displayed_domain": "fthclub.com",
            "headline": "Join 500+ Filipinos Learning The Market",
            "ad_text": "Forex is an opportunity for time and financial freedom.",
        },
        {
            "result": "relevant",
            "reason": (
                "The ad promotes Forex trading education promising financial freedom."
            ),
            "product": "Forex Trading Education",
            "category": "forex",
            "grey_signals": ["promises of financial freedom"],
        },
    )

    assert data["result"] == "not_relevant"
    assert "education" in data["reason"].casefold()


def test_scope_guard_keeps_fake_news_trading_course_funnel() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Market Secrets",
            "displayed_domain": "random-offer.example",
            "headline": "Governor reveals the secret system",
            "landing_full": "https://random-offer.example/register?utm_source=fb",
        },
        {
            "result": "relevant",
            "reason": (
                "A fake news page uses public-figure bait to promote a trading "
                "course with guaranteed profit."
            ),
            "product": "Trading course",
            "category": "trading",
            "grey_signals": [
                "fake-news style",
                "public-figure bait",
                "guaranteed profit",
                "throwaway domain",
            ],
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_rejects_disclosed_ai_dating_creative() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Dating Moments",
            "displayed_domain": "datesmoments.com",
            "headline": "Chats for women 40+",
        },
        {
            "result": "relevant",
            "reason": (
                "The ad uses an AI-Image but states that the person shown is "
                "not a platform user."
            ),
            "category": "dating",
            "grey_signals": ["fake-person impersonation"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_suspicious_whatsapp_betting_funnel() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "BcK Org",
            "displayed_domain": "bcking.site",
            "headline": "Where to play?",
            "cta": "WhatsApp",
        },
        {
            "result": "relevant",
            "reason": (
                "The betting ad uses a suspicious WhatsApp account creation funnel."
            ),
            "category": "gambling",
            "grey_signals": [
                "WhatsApp account creation funnel",
                "throwaway domain",
                "advertiser mismatch",
            ],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_consistently_branded_casino() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Casino Plus",
            "displayed_domain": "casinoplus.com.ph",
            "headline": "Win every Wednesday",
        },
        {
            "result": "relevant",
            "reason": "The ad promotes a branded online casino.",
            "category": "gambling",
            "grey_signals": ["casino bonus"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_keeps_fake_news_finance_prelander_without_visible_offer() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "LiveNews",
            "displayed_domain": "zunqavoreli.com",
            "headline": "Ana Sayfa",
            "ad_text": (
                "Teke Tek skandalı: Bakan Şimşek. Şimşek'in halka ait "
                "paraları çaldığı ortaya çıktı."
            ),
            "landing_full": "https://zunqavoreli.com/click?ad_id=123&pixel=456",
        },
        {
            "result": "relevant",
            "reason": "Fake-news public-figure prelander about public funds.",
            "category": "other_relevant",
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_rejects_generic_redirect_funnel_without_target_anchor() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Turkey Insider",
            "displayed_domain": "turkinside.com.tr",
            "headline": "Şimdi katılın",
            "ad_text": "Kolay başlangıç. Her adımda destek.",
            "landing_full": (
                "https://serinti.online/Uds5k3jj?sub1=Facebook_Mobile_Feed"
                "&utm_medium=paid&utm_source=fb"
            ),
        },
        {
            "result": "relevant",
            "reason": (
                "The ad uses an emotional video and easy start hook with a "
                "throwaway domain and Facebook tracking."
            ),
            "category": "make_money",
            "grey_signals": ["easy start", "throwaway domain", "tracking"],
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_rejects_generic_signal_word_without_target_anchor() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Turkey Insider",
            "displayed_domain": "turkinside.com.tr",
            "headline": "Şimdi katılın",
            "ad_text": "Kolay başlangıç. Her adımda destek.",
            "landing_full": "https://serinti.online/Uds5k3jj?utm_source=fb",
        },
        {
            "result": "relevant",
            "reason": "The throwaway domain is a strong signal of a hidden funnel.",
            "category": "make_money",
        },
    )

    assert data["result"] == "not_relevant"


def test_scope_guard_keeps_political_figure_hidden_prelader_with_tracking() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Pulse Türkiye",
            "displayed_domain": "oakenfield.pro",
            "headline": "Daha fazla bilgi almak için buraya tıklayın",
            "ad_text": "Kaydol",
            "landing_full": "https://oakenfield.pro/?utm_source=fb",
        },
        {
            "result": "relevant",
            "reason": (
                "The ad uses a political figure at a CHP political event "
                "with a throwaway domain and tracking."
            ),
            "category": "make_money",
        },
    )

    assert data["result"] == "relevant"


def test_scope_guard_keeps_bank_public_figure_funnel_with_tracking() -> None:
    data = apply_scope_guards(
        {
            "advertiser": "Finans Nabzı",
            "displayed_domain": "freshledger.company",
            "headline": "Buradan Arayın",
            "ad_text": "Bakiyenizi Güncelleme Fırsatı VakıfBank",
            "landing_full": (
                "https://clarabrief.info/click?ad_id=123&pixel=456"
                "&utm_medium=paid&utm_source=fb"
            ),
        },
        {
            "result": "relevant",
            "reason": "The ad uses a bank and balance update hook with a throwaway domain.",
            "category": "investing",
            "grey_signals": ["bank bait", "balance promise", "tracking"],
        },
    )

    assert data["result"] == "relevant"
