import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import redis
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.config import Settings
from app.main import create_app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/featureflags_test",
)
# Set (CI does, and docker compose provides Valkey locally) to also run every API test on Valkey.
TEST_CACHE_URL = os.getenv("TEST_CACHE_URL")
TEST_API_KEY = "test-api-key"
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    """Migrate the test database once per run, using the real Alembic migrations."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE flag_audit_events, flag_overrides, flags RESTART IDENTITY CASCADE")
        )


@pytest.fixture(params=["memory-cache", "valkey-cache"])
def settings(request: pytest.FixtureRequest) -> Settings:
    cache_url = None
    if request.param == "valkey-cache":
        if not TEST_CACHE_URL:
            pytest.skip("TEST_CACHE_URL is not set")
        client = redis.Redis.from_url(TEST_CACHE_URL)
        client.flushdb()
        client.close()
        cache_url = TEST_CACHE_URL
    return Settings(
        environment="test",
        database_url=TEST_DATABASE_URL,
        cache_url=cache_url,
        api_key=TEST_API_KEY,
    )


@pytest.fixture
def client(settings: Settings, clean_database: None) -> Iterator[TestClient]:
    with TestClient(create_app(settings), headers={"X-API-Key": TEST_API_KEY}) as test_client:
        yield test_client


@pytest.fixture
def make_flag(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _make_flag(key: str = "new-checkout", enabled: bool = False, **fields: Any) -> dict:
        payload = {"key": key, "name": fields.pop("name", key.title()), "enabled": enabled}
        response = client.post("/api/v1/flags", json=payload | fields)
        assert response.status_code == 201, response.text
        return response.json()

    return _make_flag
