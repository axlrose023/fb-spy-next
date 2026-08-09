from __future__ import annotations

from typing import Any


def funnel_status(result: dict[str, Any]) -> str:
    if result.get("success_confirmed"):
        return "success_confirmed"
    form_status = str(result.get("form_status") or "")
    if form_status in {"filled_not_submitted", "detected", "submit_domain_not_allowed"}:
        return "form_ready"
    if form_status.startswith("submitted_"):
        return "form_submitted_unconfirmed"
    if form_status == "blocked_dangerous_fields":
        return "unsafe_form_blocked"
    return str(result.get("status") or "offer_engaged")
