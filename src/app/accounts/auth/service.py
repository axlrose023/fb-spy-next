from __future__ import annotations

from .contracts import PasswordVerifier, TokenCodec, UserReader
from .exceptions import InvalidAccessToken, InvalidCredentials, UserNotAllowed
from .models import Credentials, CurrentUser, TokenPair


class AuthService:
    def __init__(
        self,
        users: UserReader,
        tokens: TokenCodec,
        passwords: PasswordVerifier,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._passwords = passwords

    async def login(self, credentials: Credentials) -> TokenPair:
        user = await self._users.get_by_username(credentials.username)
        if user is None or not user.is_active:
            raise InvalidCredentials
        if not self._passwords.verify(credentials.password, user.password_hash):
            raise InvalidCredentials
        return self._tokens.create_pair(user.id)

    async def refresh(self, refresh_token: str) -> TokenPair:
        claims = self._tokens.decode_refresh(refresh_token)
        user = await self._users.get_by_id(claims.user_id)
        if user is None or not user.is_active:
            raise UserNotAllowed
        return self._tokens.create_pair(user.id)

    async def authenticate(self, access_token: str) -> CurrentUser:
        claims = self._tokens.decode_access(access_token)
        user = await self._users.get_by_id(claims.user_id)
        if user is None or not user.is_active:
            raise InvalidAccessToken
        return user.as_current_user()

    def hash_password(self, password: str) -> str:
        return self._passwords.hash(password)
