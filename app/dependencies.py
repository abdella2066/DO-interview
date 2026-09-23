"""FastAPI dependencies: the equivalent of NestJS providers (DI) and guards."""

import secrets
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import Cache
from app.config import Settings
from app.db import get_session
from app.errors import UnauthorizedError
from app.schemas import ActorHeader
from app.service import FlagService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


def get_actor(actor: ActorHeader = None) -> str | None:
    return actor


def get_flag_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    cache: Annotated[Cache, Depends(get_cache)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    actor: Annotated[str | None, Depends(get_actor)],
) -> FlagService:
    return FlagService(session, cache, settings.cache_ttl_seconds, actor)


async def require_api_key(
    settings: Annotated[Settings, Depends(get_app_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
) -> None:
    if settings.api_key is None:
        return  # auth disabled: only possible outside production (see Settings validation)
    # compare_digest takes constant time, so response timing doesn't leak how much matched.
    if api_key is None or not secrets.compare_digest(api_key.encode(), settings.api_key.encode()):
        raise UnauthorizedError("Missing or invalid API key (send it in the X-API-Key header)")


FlagServiceDep = Annotated[FlagService, Depends(get_flag_service)]
