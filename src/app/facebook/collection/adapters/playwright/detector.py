from __future__ import annotations

import json
from importlib.resources import files

BAD_DOMAINS = (
    "google.com",
    "facebook.com",
    "fb.com",
    "fb.me",
    "youtube.com",
    "instagram.com",
    "wa.me",
    "whatsapp.com",
    "messenger.com",
)

_DETECTOR_TEMPLATE = (
    files(__package__).joinpath("detector.js").read_text(encoding="utf-8")
)
DETECT_JS = _DETECTOR_TEMPLATE.replace("%BAD%", json.dumps(list(BAD_DOMAINS)))
