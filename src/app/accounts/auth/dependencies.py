from dishka import AsyncContainer
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from .exceptions import InvalidAccessToken
from .models import CurrentUser
from .service import AuthService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


class AuthenticateUser:
    async def __call__(
        self,
        request: Request,
        token: str = Depends(oauth2_scheme),
    ) -> CurrentUser:
        container: AsyncContainer = request.state.dishka_container
        service = await container.get(AuthService)
        return await self.get_current_user(service, token)

    async def get_current_user(
        self,
        service: AuthService,
        token: str,
    ) -> CurrentUser:
        try:
            return await service.authenticate(token)
        except InvalidAccessToken as exc:
            raise self._credential_exception() from exc

    @staticmethod
    def _credential_exception() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
