import hashlib

import pytest

from app.facebook.relevance.classification.prompt import (
    PREFILTER_TEXT_PROMPT,
    PREFILTER_VISION_PROMPT,
    TEXT_PROMPT,
    VISION_PROMPT,
)

pytestmark = pytest.mark.contract


def test_relevance_prompt_snapshot() -> None:
    prompts = (
        TEXT_PROMPT,
        VISION_PROMPT,
        PREFILTER_TEXT_PROMPT,
        PREFILTER_VISION_PROMPT,
    )

    assert [hashlib.sha256(prompt.encode()).hexdigest() for prompt in prompts] == [
        "f92b909b11e5feb9e76ee0d3a94943d555bd1207164b03ae94bda270756abe6a",
        "02076600352541de8cd15618c1791a3e9f57c62f420fa8c9fa85cf8d048617a8",
        "fb6ccb62221ceb8ab0e99e5ab9d17f78003b5515481fd934166e975258b6c894",
        "972b0a9a3e20ab0561c9d583db86a20238ddbd31d9688cba84d5aeefb9a6c2a9",
    ]
