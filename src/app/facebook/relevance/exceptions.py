class RelevanceError(Exception):
    """Base error for relevance classification."""


class RelevanceProviderError(RelevanceError):
    """The configured model provider failed."""


class RelevanceProviderTimeout(RelevanceProviderError):
    """The provider did not answer before its deadline."""


class RelevanceProviderRateLimited(RelevanceProviderError):
    """The provider rejected the request because of a rate limit."""
