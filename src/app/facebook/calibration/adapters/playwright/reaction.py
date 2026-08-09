from __future__ import annotations

import time
from typing import Any, cast
from uuid import uuid4

from playwright.sync_api import Page


def click_like(page: Page, element_id: str) -> dict[str, Any]:
    result = _click_scoped_control(
        page,
        element_id=element_id,
        action="reaction",
        positive=["like", "me gusta", "beğen", "j’aime", "gefällt mir"],
        negative=[
            "unlike",
            "remove like",
            "ya no me gusta",
            "retirar me gusta",
            "beğenmekten vazgeç",
            "likepressed",
            "me gustapressed",
            "beğenpressed",
        ],
        exclude=[
            "comment",
            "comentario",
            "yorum",
            "share",
            "compartir",
            "paylaş",
            "han reaccionado",
            "have reacted",
        ],
    )
    if result.get("status") == "clicked":
        confirmation = _wait_for_active_state(
            page,
            _READ_SCOPED_CONTROL_STATE_JS,
            {
                "elementId": element_id,
                "active": [
                    "unlike",
                    "remove like",
                    "ya no me gusta",
                    "retirar me gusta",
                    "beğenmekten vazgeç",
                    "likepressed",
                    "me gustapressed",
                    "beğenpressed",
                ],
            },
            timeout_ms=8000,
        )
        if confirmation.get("status") == "active":
            result["confirmed"] = True
            result["confirmation"] = confirmation
        else:
            result = {
                "status": "click_unconfirmed",
                "action": "reaction",
                "click": result,
                "confirmation": confirmation,
            }
    return result


def _click_scoped_control(
    page: Page,
    *,
    element_id: str,
    action: str,
    positive: list[str],
    negative: list[str],
    exclude: list[str],
    timeout_ms: int = 8000,
) -> dict[str, Any]:
    marker = uuid4().hex
    result = cast(
        dict[str, Any],
        page.evaluate(
            _CLICK_CONTROL_JS,
            {
                "elementId": element_id,
                "action": action,
                "positive": positive,
                "negative": negative,
                "exclude": exclude,
                "marker": marker,
            },
        ),
    )
    if result.get("status") != "located":
        return result
    _trusted_click(page, marker, timeout_ms=timeout_ms)
    result["status"] = "clicked"
    return result


def _trusted_click(page: Page, marker: str, *, timeout_ms: int) -> None:
    control = page.locator(f'[data-fbspy-action-control="{marker}"]')
    clicked = control.evaluate(
        "element => { element.click(); return true; }",
        timeout=timeout_ms,
    )
    if not clicked:
        raise RuntimeError("action control click was not dispatched")
    page.wait_for_timeout(250)


def _wait_for_active_state(
    page: Page,
    script: str,
    payload: dict[str, Any],
    *,
    timeout_ms: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    result: dict[str, Any] = {"status": "inactive"}
    while True:
        result = cast(dict[str, Any], page.evaluate(script, payload))
        if (
            result.get("status") in {"active", "root_not_found"}
            or time.monotonic() >= deadline
        ):
            return result
        page.wait_for_timeout(400)


_CLICK_CONTROL_JS = r"""
({elementId, action, positive, negative, exclude, marker}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found", action};
  root.scrollIntoView({block: "center", inline: "nearest"});
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const controls = [...root.querySelectorAll('button,[role="button"]')];
  for (const el of controls) {
    const label = norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`);
    if (!label || exclude.some(term => label.includes(norm(term)))) continue;
    if (!positive.some(term => label.includes(norm(term)))) continue;
    const pressed = el.getAttribute("aria-pressed") === "true";
    if (pressed || negative.some(term => label.includes(norm(term)))) {
      return {status: "already_active", action, label, pressed};
    }
    el.setAttribute("data-fbspy-action-control", marker);
    return {status: "located", action, label};
  }
  return {status: "control_not_found", action};
}
"""


_READ_SCOPED_CONTROL_STATE_JS = r"""
({elementId, active}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found"};
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const controls = [...root.querySelectorAll('button,[role="button"]')];
  for (const el of controls) {
    const label = norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`);
    if (el.getAttribute("aria-pressed") === "true") {
      return {status: "active", label, pressed: true};
    }
    if (active.some(term => label.includes(norm(term)))) {
      return {status: "active", label, pressed: false};
    }
  }
  return {status: "inactive"};
}
"""
