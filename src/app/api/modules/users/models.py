from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, DateTimeMixin, UUID7IDMixin


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class User(Base, UUID7IDMixin, DateTimeMixin):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String, index=True)
    password: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(
        String(16), index=True, default=UserRole.USER.value
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value
