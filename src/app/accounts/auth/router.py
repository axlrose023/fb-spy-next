from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, HTTPException, status

from .exceptions import (
    InvalidCredentials,
    InvalidRefreshToken,
    InvalidRefreshTokenPayload,
    InvalidRefreshTokenType,
    RefreshTokenExpired,
    UserNotAllowed,
)
from .models import Credentials, TokenPair
from .schemas import LoginRequest, RefreshRequest, TokenPairResponse
from .service import AuthService

router = APIRouter(route_class=DishkaRoute)


@router.post("/login", response_model=TokenPairResponse, status_code=200)
async def login(
    request: LoginRequest,
    service: FromDishka[AuthService],
) -> TokenPairResponse:
    try:
        pair = await service.login(Credentials(request.username, request.password))
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        ) from exc
    return _response(pair)


@router.post("/refresh", response_model=TokenPairResponse, status_code=200)
async def refresh_token(
    request: RefreshRequest,
    service: FromDishka[AuthService],
) -> TokenPairResponse:
    try:
        pair = await service.refresh(request.refresh_token)
    except RefreshTokenExpired as exc:
        raise _refresh_error("Refresh token expired") from exc
    except InvalidRefreshTokenType as exc:
        raise _refresh_error("Invalid refresh token type") from exc
    except InvalidRefreshTokenPayload as exc:
        raise _refresh_error("Invalid refresh token payload") from exc
    except InvalidRefreshToken as exc:
        raise _refresh_error("Invalid refresh token") from exc
    except UserNotAllowed as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not allowed",
        ) from exc
    return _response(pair)


def _response(pair: TokenPair) -> TokenPairResponse:
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        refresh_expires_in=pair.refresh_expires_in,
    )


def _refresh_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
