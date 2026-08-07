from uuid import UUID

from app.api.modules.users.gateway import UserGateway
from app.api.modules.users.models import User

from ..models import AuthUser


class LegacyUserReader:
    def __init__(self, gateway: UserGateway) -> None:
        self._gateway = gateway

    async def get_by_username(self, username: str) -> AuthUser | None:
        return self._to_auth_user(await self._gateway.get_by_username(username))

    async def get_by_id(self, user_id: UUID) -> AuthUser | None:
        return self._to_auth_user(await self._gateway.get_by_id(user_id))

    @staticmethod
    def _to_auth_user(user: User | None) -> AuthUser | None:
        if user is None:
            return None
        return AuthUser(
            id=user.id,
            username=user.username,
            password_hash=user.password,
            role=user.role,
            is_active=user.is_active,
        )
