import re

from .exceptions import MediaRangeError

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)\Z")


def validate_range_syntax(value: str) -> None:
    match = _RANGE_RE.fullmatch(value.strip())
    if match is None or not (match.group(1) or match.group(2)):
        raise MediaRangeError


def resolve_local_range(value: str, total_size: int) -> tuple[int, int]:
    match = _RANGE_RE.fullmatch(value.strip())
    if match is None:
        raise MediaRangeError(total_size)
    first, last = match.groups()
    if first:
        start = int(first)
        end = int(last) if last else total_size - 1
        if start >= total_size or end < start:
            raise MediaRangeError(total_size)
        return start, min(end, total_size - 1)
    suffix_length = int(last)
    if suffix_length <= 0 or total_size <= 0:
        raise MediaRangeError(total_size)
    return max(0, total_size - suffix_length), total_size - 1


def total_size_from_content_range(value: str | None) -> int | None:
    if not value or "/" not in value:
        return None
    total = value.rsplit("/", 1)[-1]
    return int(total) if total.isdigit() else None
