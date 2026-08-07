from pathlib import PurePosixPath
from uuid import UUID

from ..exceptions import MediaNotFoundError
from ..models import ALLOWED_SUFFIXES, MEDIA_SPECS, MediaKind
from .validation import safe_suffix

S3_REFERENCE_PREFIX = "s3:"


def is_s3_reference(value: str | None) -> bool:
    return bool(value and value.startswith(S3_REFERENCE_PREFIX))


class ObjectKeyPolicy:
    def __init__(self, object_prefix: str) -> None:
        self._prefix = object_prefix.strip("/")
        prefix_path = PurePosixPath(self._prefix)
        if (
            not self._prefix
            or "//" in object_prefix
            or "\\" in object_prefix
            or "\x00" in object_prefix
            or any(part in {"", ".", ".."} for part in prefix_path.parts)
        ):
            raise ValueError("media object prefix must be a safe object path")

    def build(self, ad_id: UUID, kind: MediaKind, source_suffix: str) -> str:
        spec = MEDIA_SPECS[kind]
        suffix = safe_suffix(source_suffix, kind)
        return f"{self._prefix}/{ad_id}/{spec.directory}/{spec.object_stem}{suffix}"

    def reference(self, key: str) -> str:
        return f"{S3_REFERENCE_PREFIX}{key}"

    def key_for_delete(self, stored_reference: str) -> str:
        return self._validated_path(stored_reference).as_posix()

    def key_for_read(
        self,
        stored_reference: str,
        kind: MediaKind,
        expected_ad_id: UUID,
    ) -> str:
        path = self._validated_path(stored_reference)
        prefix_parts = PurePosixPath(self._prefix).parts
        media_parts = path.parts[len(prefix_parts) :]
        spec = MEDIA_SPECS[kind]
        if len(media_parts) != 3:
            raise MediaNotFoundError("invalid S3 media reference")
        ad_id, directory, filename = media_parts
        try:
            object_ad_id = UUID(ad_id)
        except ValueError as exc:
            raise MediaNotFoundError("invalid S3 media reference") from exc
        suffix = PurePosixPath(filename).suffix.casefold()
        if (
            object_ad_id != expected_ad_id
            or directory != spec.directory
            or suffix not in ALLOWED_SUFFIXES[kind]
            or filename != f"{spec.object_stem}{suffix}"
        ):
            raise MediaNotFoundError("invalid S3 media reference")
        return path.as_posix()

    def _validated_path(self, stored_reference: str) -> PurePosixPath:
        key = stored_reference.removeprefix(S3_REFERENCE_PREFIX)
        path = PurePosixPath(key)
        if (
            not key
            or path.is_absolute()
            or "//" in key
            or "\\" in key
            or "\x00" in key
            or any(part in {"", ".", ".."} for part in path.parts)
            or not key.startswith(f"{self._prefix}/")
        ):
            raise MediaNotFoundError("invalid S3 media reference")
        return path
