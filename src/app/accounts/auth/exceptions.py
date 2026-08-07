class AuthError(Exception):
    """Base error for authentication use cases."""


class InvalidCredentials(AuthError):
    pass


class InvalidAccessToken(AuthError):
    pass


class InvalidRefreshToken(AuthError):
    pass


class RefreshTokenExpired(InvalidRefreshToken):
    pass


class InvalidRefreshTokenType(InvalidRefreshToken):
    pass


class InvalidRefreshTokenPayload(InvalidRefreshToken):
    pass


class UserNotAllowed(AuthError):
    pass
