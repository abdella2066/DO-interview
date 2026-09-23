from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

FLAGS = "/api/v1/flags"


def test_create_flag_returns_201_with_location(client):
    payload = {"key": "new-checkout", "name": "New checkout", "description": "Redesign"}

    response = client.post(FLAGS, json=payload)

    assert response.status_code == 201
    assert response.headers["location"].endswith("/api/v1/flags/new-checkout")
    body = response.json()
    assert body["key"] == "new-checkout"
    assert body["name"] == "New checkout"
    assert body["description"] == "Redesign"
    assert body["enabled"] is False
    assert body["created_at"] and body["updated_at"]


def test_create_flag_can_start_enabled(client):
    response = client.post(FLAGS, json={"key": "dark-mode", "name": "Dark mode", "enabled": True})

    assert response.status_code == 201
    assert response.json()["enabled"] is True


def test_duplicate_key_returns_409(client, make_flag):
    make_flag("new-checkout")

    response = client.post(FLAGS, json={"key": "new-checkout", "name": "Again"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FLAG_ALREADY_EXISTS"


@pytest.mark.parametrize(
    "payload",
    [
        {"key": "New-Checkout", "name": "uppercase key"},
        {"key": "has space", "name": "space in key"},
        {"key": "-leading-dash", "name": "bad first character"},
        {"key": "k" * 65, "name": "key too long"},
        {"key": "ok-key", "name": "   "},
        {"key": "ok-key", "name": "n" * 101},
        {"key": "ok-key"},
        {"key": "ok-key", "name": "typo in field", "enable": True},
        {"key": "ok-key", "name": "string boolean", "enabled": "yes"},
    ],
)
def test_invalid_create_payload_returns_422(client, payload):
    response = client.post(FLAGS, json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]


def test_malformed_json_returns_400(client):
    response = client.post(
        FLAGS, content=b'{"key": "broken",', headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_JSON"


def test_get_flag(client, make_flag):
    make_flag("new-checkout")

    response = client.get(f"{FLAGS}/new-checkout")

    assert response.status_code == 200
    assert response.json()["key"] == "new-checkout"


def test_get_unknown_flag_returns_404(client):
    response = client.get(f"{FLAGS}/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FLAG_NOT_FOUND"


def test_list_flags_is_paginated_newest_first(client, make_flag):
    for key in ("first", "second", "third"):
        make_flag(key)

    page = client.get(FLAGS, params={"limit": 2}).json()
    assert page["total"] == 3
    assert [flag["key"] for flag in page["items"]] == ["third", "second"]

    next_page = client.get(FLAGS, params={"limit": 2, "offset": 2}).json()
    assert [flag["key"] for flag in next_page["items"]] == ["first"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_flags_rejects_bad_pagination(client, params):
    assert client.get(FLAGS, params=params).status_code == 422


def test_patch_disables_flag_globally(client, make_flag):
    make_flag("new-checkout", enabled=True)

    response = client.patch(f"{FLAGS}/new-checkout", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert client.get(f"{FLAGS}/new-checkout").json()["enabled"] is False


def test_patch_updates_metadata_and_updated_at(client, make_flag):
    created = make_flag("new-checkout", description="Old description")

    response = client.patch(f"{FLAGS}/new-checkout", json={"name": "v2", "description": None})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "v2"
    assert body["description"] is None
    assert body["enabled"] is False
    assert datetime.fromisoformat(body["updated_at"]) > datetime.fromisoformat(
        created["updated_at"]
    )


@pytest.mark.parametrize(
    "payload",
    [{}, {"name": None}, {"enabled": None}, {"enabled": "false"}, {"key": "renamed"}],
)
def test_invalid_patch_returns_422(client, make_flag, payload):
    make_flag("new-checkout")

    response = client.patch(f"{FLAGS}/new-checkout", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_patch_unknown_flag_returns_404(client):
    assert client.patch(f"{FLAGS}/missing", json={"enabled": True}).status_code == 404


def test_delete_flag(client, make_flag):
    make_flag("new-checkout")

    response = client.delete(f"{FLAGS}/new-checkout")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"{FLAGS}/new-checkout").status_code == 404


def test_delete_unknown_flag_returns_404(client):
    assert client.delete(f"{FLAGS}/missing").status_code == 404


def test_missing_api_key_returns_401(client):
    del client.headers["X-API-Key"]

    response = client.get(FLAGS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_wrong_api_key_returns_401(client):
    assert client.get(FLAGS, headers={"X-API-Key": "wrong-key"}).status_code == 401


def test_health_probes_do_not_need_an_api_key(client):
    del client.headers["X-API-Key"]

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_unknown_route_uses_the_error_envelope(client):
    response = client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_returns_405(client):
    response = client.put(FLAGS)

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_request_id_is_generated_or_echoed(client):
    generated = client.get(f"{FLAGS}/missing")
    assert generated.headers["x-request-id"]
    assert generated.json()["error"]["request_id"] == generated.headers["x-request-id"]

    echoed = client.get("/healthz", headers={"X-Request-ID": "trace-123"})
    assert echoed.headers["x-request-id"] == "trace-123"


def test_database_outage_returns_503(settings):
    unreachable = "postgresql+psycopg://postgres:postgres@localhost:1/nope"
    app = create_app(settings.model_copy(update={"database_url": unreachable}))

    with TestClient(app, headers={"X-API-Key": settings.api_key}) as client:
        response = client.get(FLAGS)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
