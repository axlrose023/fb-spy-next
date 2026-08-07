from datetime import timedelta

from fastapi import HTTPException, status

from app.accounts.auth.adapters import (
    BcryptPasswordVerifier,
    JwtTokenCodec,
    LegacyUserReader,
)
from app.accounts.auth.exceptions import (
    InvalidRefreshToken,
    InvalidRefreshTokenPayload,
    InvalidRefreshTokenType,
    RefreshTokenExpired,
    UserNotAllowed,
)
from app.accounts.auth.models import TokenPair
from app.accounts.auth.service import AuthService
from app.api.modules.auth.schema import TokenPairResponse
from app.api.modules.users.models import User
from app.database.uow import UnitOfWork
from app.settings import Config


class JwtService:
    """Deprecated compatibility facade for the former auth module path."""

    def __init__(self, config: Config) -> None:
        self._codec = JwtTokenCodec(
            secret_key=config.jwt.secret_key,
            algorithm=config.jwt.algorithm,
            access_ttl=timedelta(
                minutes=config.jwt.access_token_expires_in_minutes
            ),
            refresh_ttl=timedelta(minutes=config.jwt.refresh_expires_in_minutes),
        )

    def create_token_pair(self, user: User) -> TokenPairResponse:
        return self._response(self._codec.create_pair(user.id))

    def validate_refresh_token(self, refresh_token: str) -> dict:
        try:
            return self._codec.decode_refresh_payload(refresh_token)
        except RefreshTokenExpired as exc:
            raise self._error("Refresh token expired") from exc
        except InvalidRefreshTokenType as exc:
            raise self._error("Invalid refresh token type") from exc
        except InvalidRefreshToken as exc:
            raise self._error("Invalid refresh token") from exc

    async def refresh(
        self,
        refresh_token: str,
        uow: UnitOfWork,
    ) -> TokenPairResponse:
        service = AuthService(
            LegacyUserReader(uow.users),
            self._codec,
            BcryptPasswordVerifier(),
        )
        try:
            return self._response(await service.refresh(refresh_token))
        except RefreshTokenExpired as exc:
            raise self._error("Refresh token expired") from exc
        except InvalidRefreshTokenType as exc:
            raise self._error("Invalid refresh token type") from exc
        except InvalidRefreshTokenPayload as exc:
            raise self._error("Invalid refresh token payload") from exc
        except InvalidRefreshToken as exc:
            raise self._error("Invalid refresh token") from exc
        except UserNotAllowed as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not allowed",
            ) from exc

    @staticmethod
    def _response(pair: TokenPair) -> TokenPairResponse:
        return TokenPairResponse(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
            refresh_expires_in=pair.refresh_expires_in,
        )

    @staticmethod
    def _error(detail: str) -> HTTPException:
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
