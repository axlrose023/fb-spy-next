from datetime import timedelta

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.auth import (
    AccountUserReader,
    AuthService,
    BcryptPasswordVerifier,
    JwtTokenCodec,
)
from app.accounts.users import SqlAlchemyUserRepository, UserService
from app.settings import Config


class AccountsProvider(Provider):
    @provide(scope=Scope.APP)
    def get_jwt_token_codec(self, config: Config) -> JwtTokenCodec:
        return JwtTokenCodec(
            secret_key=config.jwt.secret_key,
            algorithm=config.jwt.algorithm,
            access_ttl=timedelta(minutes=config.jwt.access_token_expires_in_minutes),
            refresh_ttl=timedelta(minutes=config.jwt.refresh_expires_in_minutes),
        )

    @provide(scope=Scope.APP)
    def get_password_verifier(self) -> BcryptPasswordVerifier:
        return BcryptPasswordVerifier()

    @provide(scope=Scope.REQUEST)
    def get_user_repository(
        self,
        session: AsyncSession,
    ) -> SqlAlchemyUserRepository:
        return SqlAlchemyUserRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_auth_service(
        self,
        users: SqlAlchemyUserRepository,
        token_codec: JwtTokenCodec,
        password_verifier: BcryptPasswordVerifier,
    ) -> AuthService:
        return AuthService(
            AccountUserReader(users),
            token_codec,
            password_verifier,
        )

    @provide(scope=Scope.REQUEST)
    def get_user_service(
        self,
        users: SqlAlchemyUserRepository,
        password_verifier: BcryptPasswordVerifier,
    ) -> UserService:
        return UserService(users, password_verifier)
