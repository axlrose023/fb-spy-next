from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.params import Query

from app.accounts.auth import AuthenticateUser, CurrentUser

from .exceptions import (
    AdminRequired,
    OwnAccountRequired,
    PrivilegedFieldsRequireAdmin,
    UserError,
    UsernameTaken,
    UserNotFound,
)
from .models import CreateUser, UpdateUser, User, UserPage, UserQuery
from .schemas import (
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
    UsersPaginationParams,
    UsersPaginationResponse,
)
from .service import UserService

router = APIRouter(route_class=DishkaRoute)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    request: CreateUserRequest,
    service: FromDishka[UserService],
    current_user: CurrentUser = Depends(AuthenticateUser()),
) -> UserResponse:
    try:
        user = await service.create_user(
            CreateUser(request.username, request.password, request.role),
            actor=current_user,
        )
    except UserError as exc:
        raise _http_error(exc) from exc
    return _user_response(user)


@router.get("", response_model=UsersPaginationResponse)
async def get_users(
    service: FromDishka[UserService],
    params: Annotated[UsersPaginationParams, Query()],
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> UsersPaginationResponse:
    page = await service.list_users(
        UserQuery(
            page=params.page,
            page_size=params.page_size,
            id=params.id,
            username=params.username,
            username_search=params.username__search,
            role=params.role,
        )
    )
    return _page_response(page)


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    current_user: CurrentUser = Depends(AuthenticateUser()),
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    service: FromDishka[UserService],
    _current_user: CurrentUser = Depends(AuthenticateUser()),
    user_id: UUID = Path(...),
) -> UserResponse:
    try:
        user = await service.get_user(user_id)
    except UserError as exc:
        raise _http_error(exc) from exc
    return _user_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    request: UpdateUserRequest,
    service: FromDishka[UserService],
    current_user: CurrentUser = Depends(AuthenticateUser()),
    user_id: UUID = Path(...),
) -> UserResponse:
    try:
        user = await service.update_user(
            user_id,
            UpdateUser(
                username=request.username,
                password=request.password,
                role=request.role,
                is_active=request.is_active,
            ),
            actor=current_user,
        )
    except UserError as exc:
        raise _http_error(exc) from exc
    return _user_response(user)


def _user_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user)


def _page_response(page: UserPage) -> UsersPaginationResponse:
    return UsersPaginationResponse(
        items=[_user_response(user) for user in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
    )


def _http_error(error: UserError) -> HTTPException:
    if isinstance(error, UserNotFound):
        return HTTPException(status_code=404, detail="User not found")
    if isinstance(error, UsernameTaken):
        return HTTPException(status_code=409, detail="Username already taken")
    if isinstance(error, AdminRequired):
        return HTTPException(status_code=403, detail="Admin privileges required")
    if isinstance(error, OwnAccountRequired):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own account",
        )
    if isinstance(error, PrivilegedFieldsRequireAdmin):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can change role or activation status",
        )
    raise error
