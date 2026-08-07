from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Path
from fastapi.params import Query

from app.api.modules.auth.services.auth import AuthenticateUser
from app.api.modules.users.models import User
from app.api.modules.users.schema import (
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
    UsersPaginationParams,
    UsersPaginationResponse,
)
from app.api.modules.users.service import UserService

router = APIRouter(route_class=DishkaRoute)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    request: CreateUserRequest,
    service: FromDishka[UserService],
    current_user: User = Depends(AuthenticateUser()),
) -> UserResponse:
    return await service.create_user(request, actor=current_user)


@router.get("", response_model=UsersPaginationResponse)
async def get_users(
    service: FromDishka[UserService],
    current_user: User = Depends(AuthenticateUser()),
    params: UsersPaginationParams = Query(),
) -> UsersPaginationResponse:
    return await service.get_users(params=params)


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    current_user: User = Depends(AuthenticateUser()),
) -> UserResponse:
    return current_user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    service: FromDishka[UserService],
    current_user: User = Depends(AuthenticateUser()),
    user_id: UUID = Path(...),
) -> UserResponse:
    return await service.get_user_by_id(user_id)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    request: UpdateUserRequest,
    service: FromDishka[UserService],
    current_user: User = Depends(AuthenticateUser()),
    user_id: UUID = Path(...),
) -> UserResponse:
    return await service.update_user(user_id, request, actor=current_user)
