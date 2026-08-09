import logging
import re

_MEDIA_TOKEN_RE = re.compile(r"([?&]token=)[^&\s\"']+")


class RedactMediaTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_media_tokens(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_media_tokens(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_media_tokens(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def redact_media_tokens(value: str) -> str:
    return _MEDIA_TOKEN_RE.sub(r"\1[REDACTED]", value)
