from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.params import Query

from app.accounts.auth import AuthenticateUser
from app.api.modules.runs.schema import (
    RunImportRequest,
    RunResponse,
    RunsPaginationParams,
    RunsPaginationResponse,
    RunStartRequest,
)
from app.api.modules.runs.service import FacebookRunService
from app.api.modules.users.models import User

router = APIRouter(route_class=DishkaRoute)


@router.get("", response_model=RunsPaginationResponse)
async def get_runs(
    service: FromDishka[FacebookRunService],
    params: RunsPaginationParams = Query(),
    _current_user: User = Depends(AuthenticateUser()),
) -> RunsPaginationResponse:
    return await service.get_runs(params=params)


@router.post("", response_model=RunResponse, status_code=201)
async def start_run(
    request: RunStartRequest,
    service: FromDishka[FacebookRunService],
    current_user: User = Depends(AuthenticateUser()),
) -> RunResponse:
    _require_admin(current_user)
    return await service.start_run(request)


@router.post("/import", response_model=RunResponse, status_code=201)
async def import_run(
    request: RunImportRequest,
    service: FromDishka[FacebookRunService],
    current_user: User = Depends(AuthenticateUser()),
) -> RunResponse:
    _require_admin(current_user)
    return await service.import_run(request)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run_by_id(
    service: FromDishka[FacebookRunService],
    run_id: UUID = Path(...),
    _current_user: User = Depends(AuthenticateUser()),
) -> RunResponse:
    return await service.get_run_by_id(run_id)


@router.post("/{run_id}/stop", response_model=RunResponse)
async def stop_run(
    service: FromDishka[FacebookRunService],
    run_id: UUID = Path(...),
    current_user: User = Depends(AuthenticateUser()),
) -> RunResponse:
    _require_admin(current_user)
    return await service.stop_run(run_id)


def _require_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
