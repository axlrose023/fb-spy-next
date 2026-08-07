import logging
import re
from typing import Literal

LOG_FORMAT_DEBUG = (
    "[%(levelname)7s]: %(name)s - %(message)s --- %(pathname)s:%(lineno)d"
)
LOG_FORMAT_PROD = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_MEDIA_TOKEN_RE = re.compile(r"([?&]token=)[^&\s\"']+")


class RedactMediaTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_media_tokens(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redact_media_tokens(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact_media_tokens(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def setup_logging(env: Literal["local", "dev", "prod"]) -> None:
    """Setup logging configuration based on the environment."""
    if env in ("local", "dev"):
        logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT_DEBUG)
        logging.info("Logging is set to DEBUG level")
    else:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT_PROD)
        logging.info("Logging is set to INFO level")

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    for logger_name in ("boto3", "botocore", "s3transfer", "urllib3"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    redaction_filter = RedactMediaTokenFilter()
    logging.getLogger("uvicorn.access").addFilter(redaction_filter)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redaction_filter)


def _redact_media_tokens(value: str) -> str:
    return _MEDIA_TOKEN_RE.sub(r"\1[REDACTED]", value)
