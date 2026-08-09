import pytest

from app.facebook.relevance import apply_scope_guards

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "model", "expected"),
    [
        (
            {
                "advertiser": "National Kidney Institute",
                "displayed_domain": "health-offer.example",
                "headline": "Brain support supplement",
            },
            {
                "result": "relevant",
                "reason": "A fake news page promotes an Alzheimer miracle cure.",
                "category": "other_relevant",
            },
            "not_relevant",
        ),
        (
            {
                "advertiser": "Microsoft AI Cloud Partner Program",
                "displayed_domain": "skilling-hub.com",
                "headline": "Partner Skilling Hub",
            },
            {
                "result": "relevant",
                "reason": "The campaign discusses business revenue.",
                "category": "make_money",
            },
            "not_relevant",
        ),
        (
            {
                "advertiser": "Live TV Philippines",
                "displayed_domain": "breaking-report.example",
                "headline": "Live TV sensation: the governor scandal",
                "landing_full": "https://breaking-report.example/?ad_id=123",
            },
            {
                "result": "relevant",
                "reason": "Fake GMA Fast Talk governor scandal on a throwaway domain.",
                "category": "other_relevant",
            },
            "relevant",
        ),
        (
            {
                "advertiser": "Crypto Fund Trader",
                "displayed_domain": "cryptofundtrader.com",
                "headline": "Trade a funded account",
            },
            {
                "result": "relevant",
                "reason": "Branded prop firm with daily payouts.",
                "category": "trading",
            },
            "not_relevant",
        ),
    ],
)
def test_scope_policy_characterization(raw: dict, model: dict, expected: str) -> None:
    assert apply_scope_guards(raw, model)["result"] == expected
