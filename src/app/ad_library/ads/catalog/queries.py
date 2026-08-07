from __future__ import annotations

from ..models import Ad

_ORDER_FIELDS = frozenset(Ad.__dataclass_fields__)
_DEFAULT_ORDER = "-captured_at"


def normalize_order(value: str) -> tuple[str, bool]:
    descending = value.startswith("-")
    field = value.removeprefix("-")
    if field not in _ORDER_FIELDS:
        field = _DEFAULT_ORDER.removeprefix("-")
        descending = True
    return field, descending
