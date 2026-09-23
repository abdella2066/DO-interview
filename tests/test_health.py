from fastapi.testclient import TestClient

from app.main import create_app


def test_liveness_returns_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_is_ok_when_database_answers(client):
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_readiness_is_503_when_database_is_down(settings):
    unreachable = "postgresql+psycopg://postgres:postgres@localhost:1/nope"
    app = create_app(settings.model_copy(update={"database_url": unreachable}))

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
