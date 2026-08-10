from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.facebook.orchestration.adapters import FileLock, profile_lock_path
from app.facebook.orchestration.exceptions import ProfileLockError

pytestmark = pytest.mark.unit


def test_profile_lock_path_is_scoped_by_profile_uuid(tmp_path: Path) -> None:
    assert profile_lock_path(tmp_path, "profile-id") == (
        tmp_path / "locks" / "profile-id.lock"
    )


def test_file_lock_records_owner_and_blocks_a_second_cycle(tmp_path: Path) -> None:
    lock_path = profile_lock_path(tmp_path, "profile-id")

    with FileLock(lock_path):
        assert lock_path.read_text(encoding="utf-8") == str(os.getpid())
        with pytest.raises(ProfileLockError, match="profile locked") as captured:
            with FileLock(lock_path):
                pass

    assert captured.value.path == lock_path
    with FileLock(lock_path):
        assert lock_path.exists()


def test_file_lock_releases_when_profile_cycle_raises(tmp_path: Path) -> None:
    lock_path = profile_lock_path(tmp_path, "profile-id")

    with pytest.raises(RuntimeError, match="cycle failed"):
        with FileLock(lock_path):
            raise RuntimeError("cycle failed")

    with FileLock(lock_path):
        pass
