from uuid import UUID

from fastapi import HTTPException, status

from app.api.common.utils import build_filters
from app.api.modules.auth.service import AuthService
from app.api.modules.users.models import User
from app.api.modules.users.schema import (
    CreateUserRequest,
    UpdateUserRequest,
    UsersPaginationParams,
    UsersPaginationResponse,
)
from app.database.uow import UnitOfWork


class UserService:
    def __init__(self, uow: UnitOfWork, auth_service: AuthService):
        self.uow = uow
        self.auth_service = auth_service

    async def get_users(
        self,
        params: UsersPaginationParams,
    ) -> UsersPaginationResponse:
        pagination_data = params.model_dump(exclude_unset=True)
        pagination_data.pop("page_size", None)
        pagination_data.pop("page", None)

        filters = build_filters(User, pagination_data)

        users = await self.uow.users.get_all(
            limit=params.page_size,
            offset=params.offset,
            filters=filters,
        )
        total = await self.uow.users.get_total_count(filters)
        return UsersPaginationResponse(
            total=total,
            items=users,
            page=params.page,
            page_size=params.page_size,
        )

    async def get_user_by_id(
        self,
        user_id: UUID,
    ) -> User:
        user = await self.uow.users.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    async def create_user(self, request: CreateUserRequest, actor: User) -> User:
        self._ensure_admin(actor)
        await self._ensure_username_available(request.username)

        user = User(
            username=request.username,
            password=self.auth_service.hash_password(request.password),
            role=request.role.value,
            is_active=True,
        )
        await self.uow.users.create(user)
        await self.uow.commit()
        return user

    async def update_user(
        self,
        user_id: UUID,
        request: UpdateUserRequest,
        actor: User,
    ) -> User:
        if not actor.is_admin and actor.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own account",
            )

        # role / is_active are privileged: only an admin may change them.
        if not actor.is_admin and (
            request.role is not None or request.is_active is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an admin can change role or activation status",
            )

        user = await self.get_user_by_id(user_id)

        if request.username is not None and request.username != user.username:
            await self._ensure_username_available(request.username)
            user.username = request.username

        if request.password is not None:
            user.password = self.auth_service.hash_password(request.password)

        if request.role is not None:
            user.role = request.role.value

        if request.is_active is not None:
            user.is_active = request.is_active

        await self.uow.users.update(user)
        await self.uow.commit()
        return user

    @staticmethod
    def _ensure_admin(actor: User) -> None:
        if not actor.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required",
            )

    async def _ensure_username_available(self, username: str) -> None:
        existing = await self.uow.users.get_by_username(username)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )
