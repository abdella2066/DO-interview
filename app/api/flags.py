"""Flag CRUD. PATCH with {"enabled": true|false} is the global enable/disable, and
{"rollout_percentage": 0-100} limits an enabled flag to that share of users."""

from fastapi import APIRouter, Request, Response, status

from app.dependencies import FlagServiceDep
from app.schemas import FlagCreate, FlagKeyPath, FlagList, FlagOut, FlagUpdate, Limit, Offset

router = APIRouter(prefix="/flags", tags=["flags"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a flag")
async def create_flag(
    data: FlagCreate, service: FlagServiceDep, request: Request, response: Response
) -> FlagOut:
    flag = await service.create_flag(data)
    response.headers["Location"] = str(request.url_for("get_flag", key=flag.key))
    return FlagOut.model_validate(flag)


@router.get("", summary="List flags (newest first)")
async def list_flags(service: FlagServiceDep, limit: Limit = 50, offset: Offset = 0) -> FlagList:
    flags, total = await service.list_flags(limit, offset)
    items = [FlagOut.model_validate(flag) for flag in flags]
    return FlagList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{key}", summary="Get a flag")
async def get_flag(key: FlagKeyPath, service: FlagServiceDep) -> FlagOut:
    return FlagOut.model_validate(await service.get_flag(key))


@router.patch(
    "/{key}", summary="Update a flag, including its global enable/disable and rollout percentage"
)
async def update_flag(key: FlagKeyPath, data: FlagUpdate, service: FlagServiceDep) -> FlagOut:
    return FlagOut.model_validate(await service.update_flag(key, data))


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a flag")
async def delete_flag(key: FlagKeyPath, service: FlagServiceDep) -> Response:
    await service.delete_flag(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
