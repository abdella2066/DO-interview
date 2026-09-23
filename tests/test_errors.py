from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.main import create_app


def test_unexpected_error_returns_a_generic_500(settings):
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["message"] == "An unexpected error occurred"
    assert error["request_id"]
    assert "internal detail" not in response.text
    assert "Traceback" not in response.text


def test_slow_query_is_cancelled_by_the_statement_timeout(settings):
    app = create_app(settings.model_copy(update={"database_timeout_seconds": 1}))

    @app.get("/slow")
    async def slow(session: Annotated[AsyncSession, Depends(get_session)]) -> None:
        await session.execute(text("SELECT pg_sleep(3)"))

    with TestClient(app) as client:
        response = client.get("/slow")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
