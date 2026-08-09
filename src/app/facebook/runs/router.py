from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.params import Query

from app.accounts.auth import AuthenticateUser, CurrentUser

from .exceptions import RunArtifactsNotFound, RunNotActive, RunNotFound
from .schemas import (
    RunImportRequest,
    RunResponse,
    RunsPaginationParams,
    RunsPaginationResponse,
    RunStartRequest,
    to_import_command,
    to_page_response,
    to_query,
    to_response,
    to_start_command,
)
from .service import RunService

router = APIRouter(route_class=DishkaRoute)


@router.get("", response_model=RunsPaginationResponse)
async def get_runs(
    service: FromDishka[RunService],
    params: Annotated[RunsPaginationParams, Query()],
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> RunsPaginationResponse:
    return to_page_response(await service.list_runs(to_query(params)))


@router.post("", response_model=RunResponse, status_code=201)
async def start_run(
    request: RunStartRequest,
    service: FromDishka[RunService],
    current_user: CurrentUser = Depends(AuthenticateUser()),
) -> RunResponse:
    _require_admin(current_user)
    return to_response(await service.start_run(to_start_command(request)))


@router.post("/import", response_model=RunResponse, status_code=201)
async def import_run(
    request: RunImportRequest,
    service: FromDishka[RunService],
    current_user: CurrentUser = Depends(AuthenticateUser()),
) -> RunResponse:
    _require_admin(current_user)
    try:
        run = await service.import_run(to_import_command(request))
    except RunArtifactsNotFound as exc:
        raise HTTPException(status_code=404, detail="ads.json not found") from exc
    return to_response(run)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run_by_id(
    service: FromDishka[RunService],
    run_id: UUID = Path(...),
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> RunResponse:
    try:
        run = await service.get_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return to_response(run)


@router.post("/{run_id}/stop", response_model=RunResponse)
async def stop_run(
    service: FromDishka[RunService],
    run_id: UUID = Path(...),
    current_user: CurrentUser = Depends(AuthenticateUser()),
) -> RunResponse:
    _require_admin(current_user)
    try:
        run = await service.stop_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except RunNotActive as exc:
        raise HTTPException(status_code=409, detail="Run is not active") from exc
    return to_response(run)


def _require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
