from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from sqlalchemy import Index, Table, UniqueConstraint

from app.database.base import Base
from app.database.migrations.import_models import import_models
from app.settings import get_config

pytestmark = pytest.mark.contract

EXPECTED_TABLE_COLUMNS = {
    "facebook_ads": [
        "run_id",
        "source_index",
        "source_key",
        "advertiser",
        "ad_type",
        "format",
        "vertical",
        "country",
        "language",
        "platform",
        "placement",
        "cloaking",
        "has_video",
        "displayed_domain",
        "headline",
        "ad_text",
        "cta",
        "creative_img",
        "video_path",
        "screenshot_path",
        "screenshot_ok",
        "screenshot_issue",
        "landing_full",
        "landing_clean",
        "landing_screenshot_path",
        "landing_archive_path",
        "fb_ad_id",
        "utm",
        "captured_at",
        "id",
        "created_at",
        "updated_at",
    ],
    "facebook_runs": [
        "status",
        "title",
        "requested_minutes",
        "collect_scrolls",
        "resolve_max",
        "scroll_px",
        "debug",
        "no_resolve",
        "no_shots",
        "octo_profile_uuid",
        "profile_country",
        "octo_ip",
        "out_root",
        "runner_run_dir",
        "ads_json_path",
        "log_path",
        "debug_dir",
        "process_pid",
        "return_code",
        "error",
        "total_ads",
        "link_ads",
        "resolved_ads",
        "video_ads",
        "bad_screenshots",
        "started_at",
        "finished_at",
        "id",
        "created_at",
        "updated_at",
    ],
    "users": [
        "username",
        "password",
        "role",
        "is_active",
        "id",
        "created_at",
        "updated_at",
    ],
}
EXPECTED_METADATA_SHA256 = (
    "bcba0ca8ac3740c7abd466f3fa2e2440d686dd0fe9c596680a646e53dc58d42f"
)


def _default_contract(default: Any) -> str | None:
    if default is None:
        return None
    value = default.arg
    if callable(value):
        module = getattr(value, "__module__", "")
        name = getattr(value, "__qualname__", getattr(value, "__name__", "callable"))
        return f"{module}.{name}".strip(".")
    return str(value)


def _constraint_contract(table: Table) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            constraints.append(
                {
                    "kind": "unique",
                    "name": constraint.name,
                    "columns": sorted(column.name for column in constraint.columns),
                }
            )
    return sorted(constraints, key=lambda item: json.dumps(item, sort_keys=True))


def _index_contract(table: Table) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "name": index.name,
                "unique": index.unique,
                "columns": [column.name for column in index.columns],
            }
            for index in table.indexes
            if isinstance(index, Index)
        ),
        key=lambda item: str(item["name"]),
    )


def _metadata_contract() -> dict[str, Any]:
    import_models(get_config().paths)
    result: dict[str, Any] = {}
    for name, table in sorted(Base.metadata.tables.items()):
        result[name] = {
            "columns": [
                {
                    "name": column.name,
                    "type": str(column.type),
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "default": _default_contract(column.default),
                    "server_default": _default_contract(column.server_default),
                    "foreign_keys": sorted(
                        f"{key.target_fullname}:{key.ondelete or ''}"
                        for key in column.foreign_keys
                    ),
                }
                for column in table.columns
            ],
            "constraints": _constraint_contract(table),
            "indexes": _index_contract(table),
        }
    return result


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def test_table_and_column_contract() -> None:
    contract = _metadata_contract()
    actual = {
        table: [column["name"] for column in details["columns"]]
        for table, details in contract.items()
    }
    assert actual == EXPECTED_TABLE_COLUMNS


def test_database_metadata_contract() -> None:
    assert _digest(_metadata_contract()) == EXPECTED_METADATA_SHA256
