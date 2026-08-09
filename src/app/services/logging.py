"""Compatibility facade for the observability-owned logging API."""

from app.observability import RedactMediaTokenFilter, setup_logging

__all__ = ["RedactMediaTokenFilter", "setup_logging"]
