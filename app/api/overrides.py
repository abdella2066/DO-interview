"""Per-user overrides: enable or disable a flag for one specific user."""

from fastapi import APIRouter, Response, status

from app.dependencies import FlagServiceDep
from app.models import FlagOverride
from app.schemas import (
    FlagKeyPath,
    Limit,
    Offset,
    OverrideList,
    OverrideOut,
    OverrideSet,
    UserIdPath,
)

router = APIRouter(prefix="/flags/{key}/overrides", tags=["overrides"])


def to_override_out(key: str, override: FlagOverride) -> OverrideOut:
    return OverrideOut(
        flag_key=key,
        user_id=override.user_id,
        enabled=override.enabled,
        created_at=override.created_at,
        updated_at=override.updated_at,
    )


@router.put(
    "/{user_id}",
    summary="Enable/disable a flag for one user (201 if created, 200 if replaced)",
    responses={201: {"model": OverrideOut, "description": "Override created"}},
)
async def set_override(
    key: FlagKeyPath,
    user_id: UserIdPath,
    data: OverrideSet,
    service: FlagServiceDep,
    response: Response,
) -> OverrideOut:
    override, created = await service.set_override(key, user_id, data.enabled)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return to_override_out(key, override)


@router.get("", summary="List a flag's per-user overrides")
async def list_overrides(
    key: FlagKeyPath, service: FlagServiceDep, limit: Limit = 50, offset: Offset = 0
) -> OverrideList:
    overrides, total = await service.list_overrides(key, limit, offset)
    items = [to_override_out(key, override) for override in overrides]
    return OverrideList(items=items, total=total, limit=limit, offset=offset)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a user's override (they fall back to the global state)",
)
async def delete_override(
    key: FlagKeyPath, user_id: UserIdPath, service: FlagServiceDep
) -> Response:
    await service.delete_override(key, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
