"""Audit log: who changed a flag or its overrides, what changed, and when."""

from fastapi import APIRouter

from app.dependencies import FlagServiceDep
from app.schemas import AuditEventList, AuditEventOut, FlagKeyPath, Limit, Offset

router = APIRouter(prefix="/flags/{key}/audit", tags=["audit"])


@router.get(
    "",
    summary="List a flag's change history (newest first)",
    description="History is kept after the flag is deleted, and a key with no history returns "
    "an empty list. The actor is whatever the X-Actor header said; it isn't verified.",
)
async def list_audit_events(
    key: FlagKeyPath, service: FlagServiceDep, limit: Limit = 50, offset: Offset = 0
) -> AuditEventList:
    events, total = await service.list_audit_events(key, limit, offset)
    items = [AuditEventOut.model_validate(event) for event in events]
    return AuditEventList(items=items, total=total, limit=limit, offset=offset)
