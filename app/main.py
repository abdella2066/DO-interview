"""Application factory: wires settings, database, cache, middleware, error handling, and routes."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

from app.api import evaluate, flags, health, overrides
from app.cache import build_cache
from app.config import Settings, get_settings
from app.db import create_engine, create_session_factory
from app.dependencies import require_api_key
from app.errors import register_exception_handlers
from app.middleware import configure_logging, request_context

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.environment != "test":
        configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.cache = build_cache(settings.cache_url)
        if settings.api_key is None:
            logger.warning("API_KEY is not set: /api/v1 is unauthenticated (development only)")
        yield
        await app.state.cache.close()
        await engine.dispose()

    app = FastAPI(
        title="Feature Flag Service",
        version="1.0.0",
        description="Create feature flags, toggle them globally or per user, and evaluate them.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.middleware("http")(request_context)
    register_exception_handlers(app)

    api_v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
    api_v1.include_router(flags.router)
    api_v1.include_router(overrides.router)
    api_v1.include_router(evaluate.router)

    app.include_router(health.router)
    app.include_router(api_v1)
    return app
