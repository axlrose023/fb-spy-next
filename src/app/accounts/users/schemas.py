from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.common.schema import Pagination, PaginationParams

from .models import UserRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: UserRole
    is_active: bool


class UsersPaginationResponse(Pagination[UserResponse]):
    model_config = ConfigDict(from_attributes=True)


class UsersPaginationParams(PaginationParams):
    id: UUID | None = None
    username: str | None = None
    username__search: str | None = None
    role: UserRole | None = None


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: UserRole = UserRole.USER

    model_config = ConfigDict(extra="forbid")


class UpdateUserRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=1)
    role: UserRole | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")
