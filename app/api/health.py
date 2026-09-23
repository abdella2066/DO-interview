"""Liveness and readiness probes for App Platform and other load balancers."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.db import check_database

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    """The process is up. Checks no dependencies, so a database outage never restarts containers."""
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readiness(request: Request) -> JSONResponse:
    """Ready for traffic only when the database answers. A cache outage only degrades.

    `cache_backend` says which cache is active: the in-memory cache's ping always succeeds, so
    `"cache": "ok"` alone can't show whether a deployment is really using Valkey.
    """
    database_ok = await check_database(request.app.state.engine)
    cache = request.app.state.cache
    cache_ok = await cache.ping()
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={
            "status": "ok" if database_ok else "unavailable",
            "database": "ok" if database_ok else "unavailable",
            "cache": "ok" if cache_ok else "degraded",
            "cache_backend": cache.backend,
        },
    )
