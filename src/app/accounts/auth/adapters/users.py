from uuid import UUID

from app.accounts.users import UserAccount, UserRepository

from ..models import AuthUser


class AccountUserReader:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def get_by_username(self, username: str) -> AuthUser | None:
        return self._to_auth_user(await self._users.get_by_username(username))

    async def get_by_id(self, user_id: UUID) -> AuthUser | None:
        return self._to_auth_user(await self._users.get_by_id(user_id))

    @staticmethod
    def _to_auth_user(user: UserAccount | None) -> AuthUser | None:
        if user is None:
            return None
        return AuthUser(
            id=user.id,
            username=user.username,
            password_hash=user.password_hash,
            role=user.role.value,
            is_active=user.is_active,
        )
