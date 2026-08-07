from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from .exceptions import (
    MediaNotFoundError,
    MediaRangeError,
    MediaStorageError,
    MediaTokenError,
)
from .models import MEDIA_SPECS, MediaKind
from .service import MediaService
from .streaming import iter_media_body

router = APIRouter(route_class=DishkaRoute)


@router.get(
    "/ads/{ad_id}/{kind}",
    response_class=StreamingResponse,
    operation_id="get_ad_media",
)
@router.head(
    "/ads/{ad_id}/{kind}",
    response_class=StreamingResponse,
    operation_id="head_ad_media",
)
async def get_ad_media(
    request: Request,
    service: FromDishka[MediaService],
    ad_id: UUID = Path(...),
    kind: MediaKind = Path(...),
    token: str = Query(..., min_length=45, max_length=80),
) -> Response:
    try:
        payload = await service.get_media(
            ad_id,
            kind,
            token,
            range_header=request.headers.get("range"),
            head_only=request.method == "HEAD",
        )
    except MediaTokenError as exc:
        raise HTTPException(status_code=403, detail="Invalid media link") from exc
    except MediaRangeError as exc:
        headers = {}
        if exc.total_size is not None:
            headers["Content-Range"] = f"bytes */{exc.total_size}"
        raise HTTPException(
            status_code=416,
            detail="Requested range is not satisfiable",
            headers=headers,
        ) from exc
    except MediaNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Media not found") from exc
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=502,
            detail="Media storage is temporarily unavailable",
        ) from exc

    spec = MEDIA_SPECS[kind]
    disposition = "attachment" if spec.attachment else "inline"
    filename = f"ad-{ad_id}-{spec.object_stem}{spec.default_suffix}"
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600, no-transform",
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Length": str(payload.content_length),
        "Cross-Origin-Resource-Policy": "same-origin",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if payload.content_range:
        headers["Content-Range"] = payload.content_range
    if request.method == "HEAD":
        payload.body.close()
        return Response(
            status_code=payload.status_code,
            headers=headers,
            media_type=payload.content_type,
        )
    return StreamingResponse(
        iter_media_body(payload.body),
        status_code=payload.status_code,
        headers=headers,
        media_type=payload.content_type,
    )
