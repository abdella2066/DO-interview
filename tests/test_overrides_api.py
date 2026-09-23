from datetime import datetime

import pytest

OVERRIDES = "/api/v1/flags/new-checkout/overrides"


def test_put_override_creates_then_replaces(client, make_flag):
    make_flag("new-checkout")

    created = client.put(f"{OVERRIDES}/user-1", json={"enabled": True})
    assert created.status_code == 201
    assert created.json()["flag_key"] == "new-checkout"
    assert created.json()["user_id"] == "user-1"
    assert created.json()["enabled"] is True

    replaced = client.put(f"{OVERRIDES}/user-1", json={"enabled": False})
    assert replaced.status_code == 200
    assert replaced.json()["enabled"] is False
    assert replaced.json()["created_at"] == created.json()["created_at"]
    assert datetime.fromisoformat(replaced.json()["updated_at"]) > datetime.fromisoformat(
        created.json()["updated_at"]
    )


def test_override_on_unknown_flag_returns_404(client):
    response = client.put("/api/v1/flags/missing/overrides/user-1", json={"enabled": True})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FLAG_NOT_FOUND"


@pytest.mark.parametrize("user_id", ["has space", "u" * 129, "semi;colon"])
def test_invalid_user_id_returns_422(client, make_flag, user_id):
    make_flag("new-checkout")

    response = client.put(f"{OVERRIDES}/{user_id}", json={"enabled": True})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload", [{}, {"enabled": "true"}, {"enabled": None}, {"enabled": True, "extra": 1}]
)
def test_invalid_override_body_returns_422(client, make_flag, payload):
    make_flag("new-checkout")

    response = client.put(f"{OVERRIDES}/user-1", json=payload)

    assert response.status_code == 422


def test_list_overrides_sorted_by_user(client, make_flag):
    make_flag("new-checkout")
    client.put(f"{OVERRIDES}/bob", json={"enabled": False})
    client.put(f"{OVERRIDES}/alice", json={"enabled": True})

    body = client.get(OVERRIDES).json()

    assert body["total"] == 2
    assert [(item["user_id"], item["enabled"]) for item in body["items"]] == [
        ("alice", True),
        ("bob", False),
    ]


def test_list_overrides_for_unknown_flag_returns_404(client):
    assert client.get("/api/v1/flags/missing/overrides").status_code == 404


def test_delete_override(client, make_flag):
    make_flag("new-checkout")
    client.put(f"{OVERRIDES}/user-1", json={"enabled": True})

    assert client.delete(f"{OVERRIDES}/user-1").status_code == 204

    again = client.delete(f"{OVERRIDES}/user-1")
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "OVERRIDE_NOT_FOUND"


def test_deleting_a_flag_deletes_its_overrides(client, make_flag):
    make_flag("new-checkout")
    client.put(f"{OVERRIDES}/user-1", json={"enabled": True})

    client.delete("/api/v1/flags/new-checkout")
    make_flag("new-checkout")

    assert client.get(OVERRIDES).json()["total"] == 0
