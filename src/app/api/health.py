from fastapi import APIRouter

router = APIRouter()


@router.get("/ping")
async def ping() -> None | dict:
    """Ping endpoint to check if the service is alive."""
    return {"message": "pong"}
