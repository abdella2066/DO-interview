import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize("scheme", ["postgresql://", "postgres://"])
def test_digitalocean_database_url_gets_the_psycopg_driver(scheme):
    settings = Settings(
        _env_file=None, database_url=f"{scheme}u:p@db.example:25060/app?sslmode=require"
    )

    assert settings.database_url == "postgresql+psycopg://u:p@db.example:25060/app?sslmode=require"


def test_production_refuses_to_start_without_an_api_key():
    with pytest.raises(ValidationError, match="API_KEY must be set"):
        Settings(_env_file=None, environment="production", api_key=None)


def test_blank_optional_values_mean_unset():
    settings = Settings(_env_file=None, cache_url="", api_key="")

    assert settings.cache_url is None
    assert settings.api_key is None
