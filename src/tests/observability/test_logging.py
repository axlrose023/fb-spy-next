import logging

import pytest

from app.observability import RedactMediaTokenFilter, setup_logging
from app.services import logging as legacy_logging

pytestmark = pytest.mark.unit


def test_media_token_is_redacted_from_access_log_arguments() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            "/media/ads/example/screenshot?token=123.secret&download=1",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    assert RedactMediaTokenFilter().filter(record) is True
    rendered = record.getMessage()

    assert "123.secret" not in rendered
    assert "token=[REDACTED]&download=1" in rendered


def test_storage_sdk_wire_logging_is_never_enabled() -> None:
    setup_logging("local")

    for logger_name in ("boto3", "botocore", "s3transfer", "urllib3"):
        assert logging.getLogger(logger_name).level >= logging.WARNING


def test_legacy_logging_module_is_an_identity_preserving_facade() -> None:
    assert legacy_logging.RedactMediaTokenFilter is RedactMediaTokenFilter
    assert legacy_logging.setup_logging is setup_logging
