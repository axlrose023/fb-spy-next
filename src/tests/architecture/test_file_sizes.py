from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

SRC_ROOT = Path(__file__).parents[2]
PRODUCTION_ROOTS = tuple(
    SRC_ROOT / "app" / name
    for name in ("accounts", "ad_library", "facebook", "observability")
)
TEST_ROOTS = tuple(
    SRC_ROOT / "tests" / name
    for name in ("accounts", "ad_library", "facebook", "observability")
)
SIZE_EXCEPTIONS: dict[str, tuple[int, str]] = {}


def _python_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if root.exists():
            yield from sorted(root.rglob("*.py"))


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _production_limit(path: Path) -> int:
    return 300 if "adapters" in path.parts else 250


def _allowed_size(path: Path, default: int) -> int:
    relative = path.relative_to(SRC_ROOT).as_posix()
    exception = SIZE_EXCEPTIONS.get(relative)
    return exception[0] if exception else default


def test_new_production_files_stay_small() -> None:
    violations: list[str] = []
    for path in _python_files(PRODUCTION_ROOTS):
        actual = _line_count(path)
        allowed = _allowed_size(path, _production_limit(path))
        if actual > allowed:
            relative = path.relative_to(SRC_ROOT)
            violations.append(f"{relative}: {actual} lines, maximum {allowed}")
    assert not violations, "Split oversized production files:\n" + "\n".join(violations)


def test_new_test_files_stay_below_test_limit() -> None:
    violations: list[str] = []
    for path in _python_files(TEST_ROOTS):
        actual = _line_count(path)
        allowed = _allowed_size(path, 450)
        if actual > allowed:
            relative = path.relative_to(SRC_ROOT)
            violations.append(f"{relative}: {actual} lines, maximum {allowed}")
    assert not violations, "Split oversized test files:\n" + "\n".join(violations)


def test_size_exceptions_are_documented_and_current() -> None:
    stale: list[str] = []
    for relative, (limit, reason) in SIZE_EXCEPTIONS.items():
        path = SRC_ROOT / relative
        if not path.is_file() or _line_count(path) <= _production_limit(path):
            stale.append(relative)
        assert limit > 0 and reason.strip(), f"Invalid size exception: {relative}"
    assert not stale, "Remove stale size exceptions: " + ", ".join(stale)
