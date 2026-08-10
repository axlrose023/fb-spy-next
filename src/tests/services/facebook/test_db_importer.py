from datetime import UTC

from app.facebook.runs.commands import _default_title, _parse_datetime


def test_db_importer_builds_profile_title_and_parses_utc(tmp_path) -> None:
    assert _default_title(
        {"profile_country": "Spain"},
        tmp_path / "collect_1",
    ).endswith("Spain - collect_1")
    parsed = _parse_datetime("2026-07-14T12:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo == UTC
