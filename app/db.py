"""Database engine, session factory, and the per-request session dependency."""

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT_SECONDS = 3.0


def create_engine(database_url: str, timeout_seconds: int) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=timeout_seconds,
        connect_args={
            "connect_timeout": timeout_seconds,
            # Postgres cancels any statement that runs longer, so a slow query can't hang a request.
            "options": f"-c statement_timeout={timeout_seconds * 1000}",
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine) -> bool:
    try:
        async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_SECONDS), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return False


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session
