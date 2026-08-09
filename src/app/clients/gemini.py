"""Compatibility import for the relevance-owned Gemini adapter."""

from app.facebook.relevance.adapters import gemini as _adapter

GeminiClient = _adapter.GeminiRelevanceProvider
genai = _adapter.genai
_UPLOAD_POLL_INTERVAL_S = _adapter._UPLOAD_POLL_INTERVAL_S

__all__ = ["GeminiClient"]
