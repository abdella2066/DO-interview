"""Evaluation: is this flag on for this user? The hot path, served from the cache when possible."""

from fastapi import APIRouter, Response

from app.dependencies import FlagServiceDep
from app.schemas import (
    EvaluationOut,
    FlagKeyPath,
    UserFlag,
    UserFlagsOut,
    UserIdPath,
    UserIdQuery,
)

router = APIRouter(tags=["evaluation"])


@router.get(
    "/flags/{key}/evaluate",
    summary="Evaluate a flag for a user",
    description="Precedence: the user's override if one exists; otherwise off if the flag is "
    "disabled; otherwise on for everyone at a 100% rollout, or for the users inside a smaller "
    "rollout percentage (reason ROLLOUT). "
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


@router.get(
    "/users/{user_id}/flags",
    summary="Evaluate every flag for a user",
    description="One call for SDKs to load all flags for a user, sorted by key. "
    "Same precedence as single evaluation.",
)
async def evaluate_all_flags(user_id: UserIdPath, service: FlagServiceDep) -> UserFlagsOut:
    results = await service.evaluate_all(user_id)
    flags = [
        UserFlag(flag_key=key, enabled=result.enabled, reason=result.reason)
        for key, result in results
    ]
    return UserFlagsOut(user_id=user_id, flags=flags)
