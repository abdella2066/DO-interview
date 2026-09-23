"""Evaluation: is this flag on for this user? The hot path, served from the cache when possible."""

from fastapi import APIRouter, Response

from app.dependencies import FlagServiceDep
from app.schemas import EvaluationOut, FlagKeyPath, UserIdQuery

router = APIRouter(tags=["evaluation"])


@router.get(
    "/flags/{key}/evaluate",
    summary="Evaluate a flag for a user",
    description="Precedence: the user's override if one exists, otherwise the global state. "
    "The X-Cache response header is HIT when the flag was served from the cache.",
)
async def evaluate_flag(
    key: FlagKeyPath, user_id: UserIdQuery, service: FlagServiceDep, response: Response
) -> EvaluationOut:
    result, cache_hit = await service.evaluate(key, user_id)
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    return EvaluationOut(
        flag_key=key, user_id=user_id, enabled=result.enabled, reason=result.reason
    )
