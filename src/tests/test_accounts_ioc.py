from __future__ import annotations

import pytest

from app.accounts.auth import AuthService
from app.accounts.auth.adapters import BcryptPasswordVerifier, JwtTokenCodec
from app.accounts.ioc import AccountsProvider
from app.accounts.users import UserService
from app.accounts.users.adapters.persistence import SqlAlchemyUserRepository
from app.ioc import get_async_container

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_root_container_resolves_accounts_graph() -> None:
    assert AccountsProvider is not None
    container = get_async_container()
    try:
        async with container() as request:
            repository = await request.get(SqlAlchemyUserRepository)
            token_codec = await request.get(JwtTokenCodec)
            password_verifier = await request.get(BcryptPasswordVerifier)
            auth_service = await request.get(AuthService)
            user_service = await request.get(UserService)

            assert isinstance(repository, SqlAlchemyUserRepository)
            assert isinstance(token_codec, JwtTokenCodec)
            assert isinstance(password_verifier, BcryptPasswordVerifier)
            assert isinstance(auth_service, AuthService)
            assert isinstance(user_service, UserService)
    finally:
        await container.close()
