class AdError(Exception):
    pass


class AdNotFoundError(AdError, LookupError):
    pass
