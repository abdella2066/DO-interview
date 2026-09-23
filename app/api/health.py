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
    """Ready for traffic only when the database answers."""
    database_ok = await check_database(request.app.state.engine)
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={
            "status": "ok" if database_ok else "unavailable",
            "database": "ok" if database_ok else "unavailable",
        },
    )
