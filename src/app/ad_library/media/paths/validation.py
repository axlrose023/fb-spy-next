import mimetypes
from pathlib import Path

from ..exceptions import MediaNotFoundError
from ..models import ALLOWED_SUFFIXES, MEDIA_SPECS, MediaKind


class LocalPathPolicy:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.expanduser().resolve()

    def resolve(self, stored_reference: str) -> Path:
        candidate = Path(stored_reference).expanduser()
        if not candidate.is_absolute():
            candidate = self._data_dir / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._data_dir)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise MediaNotFoundError("invalid local media reference") from exc
        return resolved


def safe_suffix(value: str, kind: MediaKind) -> str:
    suffix = value.casefold()
    return (
        suffix if suffix in ALLOWED_SUFFIXES[kind] else MEDIA_SPECS[kind].default_suffix
    )


def content_type(kind: MediaKind, suffix: str) -> str:
    guessed, _ = mimetypes.guess_type(f"file{safe_suffix(suffix, kind)}")
    return guessed or MEDIA_SPECS[kind].default_content_type
