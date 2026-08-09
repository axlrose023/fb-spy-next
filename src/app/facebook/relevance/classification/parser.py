from __future__ import annotations

import json
from typing import Any

from ..models import RelevanceDecision

_BINARY_RESULTS = {
    RelevanceDecision.RELEVANT.value,
    RelevanceDecision.NOT_RELEVANT.value,
}


def parse_model_json(
    text: str,
    *,
    allowed_results: set[str] | None = None,
) -> dict[str, Any]:
    response = (text or "").strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return {
            "result": RelevanceDecision.NOT_RELEVANT.value,
            "reason": response[:240] or "Invalid model JSON",
        }
    if not isinstance(data, dict):
        return {
            "result": RelevanceDecision.NOT_RELEVANT.value,
            "reason": "Invalid model JSON",
        }
    accepted = allowed_results or _BINARY_RESULTS
    result = str(data.get("result") or "not_relevant").lower()
    if result not in accepted:
        result = RelevanceDecision.NOT_RELEVANT.value
    data["result"] = result
    if not data.get("reason"):
        data["reason"] = "No reason provided."
    return data
