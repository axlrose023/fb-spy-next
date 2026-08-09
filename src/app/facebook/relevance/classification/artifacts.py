from __future__ import annotations

from pathlib import Path
from typing import Any


def first_existing_path(
    run_dir: Path,
    raw: dict[str, Any],
    keys: tuple[str, ...],
) -> Path | None:
    for key in keys:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value)
        if not path.is_absolute():
            path = run_dir / path
        if path.exists():
            return path
    return None


def existing_paths(
    run_dir: Path,
    raw: dict[str, Any],
    keys: tuple[str, ...],
) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for key in keys:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value)
        if not path.is_absolute():
            path = run_dir / path
        path = path.resolve()
        if path.exists() and path not in seen:
            paths.append((key, path))
            seen.add(path)
    return paths
