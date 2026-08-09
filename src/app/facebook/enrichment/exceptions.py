class EnrichmentError(Exception):
    """Base error for relevant-only ad enrichment."""


class RelevanceGateDenied(EnrichmentError):
    """An ad was not approved for authenticated browser actions."""


class EnrichmentInfrastructureError(EnrichmentError):
    """The browser, profile, proxy, or network infrastructure failed."""
