from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType

from ..exceptions import ProfileLockError


class FileLock:
    """Non-blocking process lock used to serialize one profile cycle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.fd)
            self.fd = None
            raise ProfileLockError(self.path) from exc
        os.ftruncate(self.fd, 0)
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self.fd is None:
            return
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None


def profile_lock_path(root_dir: Path, profile_uuid: str) -> Path:
    return root_dir / "locks" / f"{profile_uuid}.lock"
