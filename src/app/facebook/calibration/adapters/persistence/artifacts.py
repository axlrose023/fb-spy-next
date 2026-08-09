from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ...planning import CalibrationTarget


def write_targets(path: Path, targets: list[CalibrationTarget]) -> None:
    write_json_atomic(path, [asdict(target) for target in targets])


def write_json(path: Path, payload: Any) -> None:
    write_json_atomic(path, payload)


def append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    os.chmod(path, 0o600)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
