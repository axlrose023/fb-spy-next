"""Compatibility entrypoint for importing a classified orchestrator run."""

from app.facebook.runs.commands import (
    _default_title,
    _load_json,
    _parse_datetime,
    import_run,
    main,
)

__all__ = [
    "_default_title",
    "_load_json",
    "_parse_datetime",
    "import_run",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
