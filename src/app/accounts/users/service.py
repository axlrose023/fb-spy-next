from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from .contracts import PasswordHasher, UserActor, UserRepository
from .exceptions import (
    AdminRequired,
    OwnAccountRequired,
    PrivilegedFieldsRequireAdmin,
    UsernameTaken,
    UserNotFound,
)
from .models import (
    CreateUser,
    NewUser,
    UpdateUser,
    User,
    UserAccount,
    UserPage,
    UserQuery,
)


class UserService:
    def __init__(self, users: UserRepository, passwords: PasswordHasher) -> None:
        self._users = users
        self._passwords = passwords

    async def list_users(self, query: UserQuery) -> UserPage:
        accounts = await self._users.list_users(query)
        total = await self._users.count_users(query)
        return UserPage(
            items=tuple(account.as_user() for account in accounts),
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def get_user(self, user_id: UUID) -> User:
        return (await self._account(user_id)).as_user()

    async def create_user(self, command: CreateUser, actor: UserActor) -> User:
        if not actor.is_admin:
            raise AdminRequired
        await self._ensure_username_available(command.username)
        account = await self._users.create(
            NewUser(
                username=command.username,
                password_hash=self._passwords.hash(command.password),
                role=command.role,
            )
        )
        return account.as_user()

    async def update_user(
        self,
        user_id: UUID,
        command: UpdateUser,
        actor: UserActor,
    ) -> User:
        self._authorize_update(user_id, command, actor)
        account = await self._account(user_id)

        username = account.username
        if command.username is not None and command.username != account.username:
            await self._ensure_username_available(command.username)
            username = command.username

        updated = replace(
            account,
            username=username,
            password_hash=(
                self._passwords.hash(command.password)
                if command.password is not None
                else account.password_hash
            ),
            role=command.role if command.role is not None else account.role,
            is_active=(
                command.is_active
                if command.is_active is not None
                else account.is_active
            ),
        )
        persisted = await self._users.update(updated)
        if persisted is None:
            raise UserNotFound
        return persisted.as_user()

    async def _account(self, user_id: UUID) -> UserAccount:
        account = await self._users.get_by_id(user_id)
        if account is None:
            raise UserNotFound
        return account

    async def _ensure_username_available(self, username: str) -> None:
        if await self._users.get_by_username(username) is not None:
            raise UsernameTaken

    @staticmethod
    def _authorize_update(
        user_id: UUID,
        command: UpdateUser,
        actor: UserActor,
    ) -> None:
        if not actor.is_admin and actor.id != user_id:
            raise OwnAccountRequired
        if not actor.is_admin and command.changes_privileged_fields:
            raise PrivilegedFieldsRequireAdmin
