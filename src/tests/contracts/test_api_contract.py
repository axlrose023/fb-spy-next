from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.contract

EXPECTED_ROUTE_METHODS = {
    "/ads": ["GET"],
    "/ads/{ad_id}": ["GET"],
    "/auth/login": ["POST"],
    "/auth/refresh": ["POST"],
    "/media/ads/{ad_id}/{kind}": ["GET", "HEAD"],
    "/metrics": ["GET"],
    "/ping": ["GET"],
    "/runs": ["GET", "POST"],
    "/runs/import": ["POST"],
    "/runs/{run_id}": ["GET"],
    "/runs/{run_id}/stop": ["POST"],
    "/stats/ads": ["GET"],
    "/users": ["GET", "POST"],
    "/users/me": ["GET"],
    "/users/{user_id}": ["GET", "PATCH"],
}
EXPECTED_OPENAPI_SHA256 = (
    "51b4673b6cf4583d358e520d6727a31c74154fd1fddfcee29576b1eed2754644"
)
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def test_public_route_and_method_contract(app: FastAPI) -> None:
    schema = app.openapi()
    actual = {
        path: sorted(method.upper() for method in data if method in HTTP_METHODS)
        for path, data in sorted(schema["paths"].items())
    }
    assert actual == EXPECTED_ROUTE_METHODS


def test_openapi_schema_contract(app: FastAPI) -> None:
    assert _canonical_digest(app.openapi()) == EXPECTED_OPENAPI_SHA256
