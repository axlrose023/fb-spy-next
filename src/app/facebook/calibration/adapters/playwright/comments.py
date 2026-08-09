from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from playwright.sync_api import Locator, Page

from .reaction import _click_scoped_control, _trusted_click


def post_comment(page: Page, element_id: str, text: str) -> dict[str, Any]:
    opened = _click_scoped_control(
        page,
        element_id=element_id,
        action="comment",
        positive=["comment", "comentario", "comentar", "yorum"],
        negative=[],
        exclude=[
            "comments and reactions",
            "comentarios y reacciones",
            "people reacted",
            "people have reacted",
            "personas han reaccionado",
        ],
    )
    if opened.get("status") != "clicked":
        return opened
    composer, composer_scope = _wait_for_comment_composer(
        page,
        element_id,
        timeout_ms=5000,
    )
    if composer is None:
        return {"status": "composer_not_found", "control": opened}
    before_count = page.evaluate(_COUNT_EXACT_TEXT_JS, text)
    composer.fill(text)
    marker = uuid4().hex
    submit = composer.evaluate(
        _LOCATE_COMMENT_SUBMIT_JS,
        {
            "marker": marker,
            "positive": [
                "post comment",
                "publish comment",
                "send comment",
                "post",
                "send",
                "publicar comentario",
                "publicar comentário",
                "publicar",
                "enviar",
                "yorum paylaş",
                "gönder",
                "paylaş",
                "i-post",
                "publier le commentaire",
                "kommentar posten",
            ],
        },
    )
    if submit.get("status") == "located":
        _trusted_click(page, marker, timeout_ms=8000)
    else:
        try:
            composer.press("Enter")
            submit = {
                "status": "keyboard_submitted",
                "action": "comment_submit",
            }
        except Exception as exc:
            composer.fill("")
            return {
                "status": "submit_control_not_found",
                "control": opened,
                "submit": submit,
                "keyboard_error": repr(exc),
            }
    confirmed = False
    remaining = text
    for _ in range(60):
        page.wait_for_timeout(500)
        try:
            remaining = (
                composer.input_value()
                if composer.evaluate("el => el.tagName") == "TEXTAREA"
                else composer.inner_text()
            )
        except Exception:
            remaining = ""
        state = page.evaluate(_COMMENT_SUBMISSION_STATE_JS, text)
        if (
            not remaining.strip()
            and state.get("count", 0) > before_count
            and not state.get("pending")
        ):
            confirmed = True
            break
    if not confirmed:
        try:
            if remaining.strip():
                composer.fill("")
        except Exception:
            pass
        state = page.evaluate(_COMMENT_SUBMISSION_STATE_JS, text)
        return {
            "status": "submit_unconfirmed",
            "control": opened,
            "submit": submit,
            "composer_scope": composer_scope,
            "composer_remaining": remaining.strip(),
            "before_count": before_count,
            "after_count": state.get("count", 0),
            "pending": bool(state.get("pending")),
        }
    return {
        "status": "posted",
        "text": text,
        "control": opened,
        "submit": submit,
        "composer_scope": composer_scope,
    }


def _first_visible(scope: Locator | Page, selector: str) -> Locator | None:
    for locator in scope.locator(selector).all():
        try:
            if locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def _wait_for_comment_composer(
    page: Page,
    element_id: str,
    *,
    timeout_ms: int,
) -> tuple[Locator | None, str]:
    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    while True:
        root = page.locator(f'[data-fbspy-id="{element_id}"]').first
        composer = _first_visible(root, _COMMENT_COMPOSER_SELECTOR)
        if composer is not None:
            return composer, "post"
        composer = _first_visible(page, _COMMENT_COMPOSER_SELECTOR)
        if composer is not None:
            return composer, "comments_screen"
        if time.monotonic() >= deadline:
            return None, "not_found"
        page.wait_for_timeout(250)


_COMMENT_COMPOSER_SELECTOR = (
    "textarea, [contenteditable='true'][role='textbox'], "
    "[contenteditable='true'][role='combobox']"
)

_COUNT_EXACT_TEXT_JS = r"""
text => {
  const value = String(text || "");
  if (!value) return 0;
  const haystack = document.body?.innerText || "";
  return haystack.split(value).length - 1;
}
"""

_COMMENT_SUBMISSION_STATE_JS = r"""
text => {
  const value = String(text || "");
  const haystack = document.body?.innerText || "";
  const folded = haystack.toLocaleLowerCase();
  const pendingTerms = [
    "posting", "sending", "publicando", "enviando", "paylaşılıyor",
    "publication en cours", "wird gepostet",
  ];
  return {
    count: value ? haystack.split(value).length - 1 : 0,
    pending: pendingTerms.some(term => folded.includes(term)),
  };
}
"""

_LOCATE_COMMENT_SUBMIT_JS = r"""
(composer, {marker, positive}) => {
  const norm = value => (value || "").toLocaleLowerCase()
    .replace(/\s+/g, " ").trim();
  const wanted = positive.map(norm);
  for (let root = composer.parentElement, depth = 0;
       root && root !== document.body && depth < 8;
       root = root.parentElement, depth += 1) {
    const controls = root.querySelectorAll(
      'button,[role="button"],input[type="submit"]'
    );
    for (const control of controls) {
      const rect = control.getBoundingClientRect();
      if (rect.width < 16 || rect.height < 16) continue;
      if (control.disabled || control.getAttribute("aria-disabled") === "true") {
        continue;
      }
      const label = norm(
        `${control.getAttribute("aria-label") || ""} ` +
        `${control.getAttribute("title") || ""} ` +
        `${control.getAttribute("value") || ""} ${control.innerText || ""}`
      );
      const typedSubmit = control.matches(
        'button[type="submit"],input[type="submit"]'
      );
      if (
        !typedSubmit
        && !wanted.some(term => label === term || label.includes(term))
      ) {
        continue;
      }
      control.setAttribute("data-fbspy-action-control", marker);
      return {
        status: "located",
        action: "comment_submit",
        label,
        depth,
        strategy: typedSubmit ? "submit_type" : "accessible_label",
      };
    }
  }
  return {status: "submit_control_not_found", action: "comment_submit"};
}
"""
