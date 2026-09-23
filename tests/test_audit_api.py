from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_actor
from app.main import create_app

FLAGS = "/api/v1/flags"
FLAG = f"{FLAGS}/new-checkout"
AUDIT = f"{FLAG}/audit"
ALICE = {"X-Actor": "alice@example.com"}
NEW_FLAG = {"key": "new-checkout", "name": "New checkout"}
CREATED_DETAILS = {
    "name": "New checkout",
    "description": None,
    "enabled": False,
    "rollout_percentage": 100,
}


def history(client):
    events = client.get(AUDIT).json()["items"]
    return [(event["action"], event["actor"], event["details"]) for event in events]


def test_every_change_writes_an_event_with_actor_and_details(client):
    client.post(FLAGS, json=NEW_FLAG, headers=ALICE)
    client.patch(FLAG, json={"enabled": True, "rollout_percentage": 25}, headers=ALICE)
    client.put(f"{FLAG}/overrides/user-1", json={"enabled": False}, headers=ALICE)
    client.delete(f"{FLAG}/overrides/user-1", headers=ALICE)
    client.delete(FLAG, headers=ALICE)

    assert history(client) == [
        ("flag.deleted", "alice@example.com", {}),
        ("override.deleted", "alice@example.com", {"user_id": "user-1"}),
        ("override.set", "alice@example.com", {"user_id": "user-1", "enabled": False}),
        ("flag.updated", "alice@example.com", {"enabled": True, "rollout_percentage": 25}),
        ("flag.created", "alice@example.com", CREATED_DETAILS),
    ]


def test_update_records_only_the_fields_that_changed(client, make_flag):
    make_flag("new-checkout", name="New checkout")

    client.patch(FLAG, json={"name": "New checkout", "enabled": True})

    assert history(client)[0] == ("flag.updated", None, {"enabled": True})


def test_update_that_changes_nothing_writes_no_event(client, make_flag):
    make_flag("new-checkout", enabled=True)

    assert client.patch(FLAG, json={"enabled": True}).status_code == 200
    assert [action for action, _, _ in history(client)] == ["flag.created"]


def test_actor_is_null_without_the_header(client):
    client.post(FLAGS, json=NEW_FLAG)

    assert history(client) == [("flag.created", None, CREATED_DETAILS)]


@pytest.mark.parametrize("actor", ["Jane Doe (on-call)", "a" * 100], ids=["spaces", "100-chars"])
def test_actor_is_recorded_as_sent(client, actor):
    client.post(FLAGS, json=NEW_FLAG, headers={"X-Actor": actor})

    assert history(client) == [("flag.created", actor, CREATED_DETAILS)]


@pytest.mark.parametrize(
    "actor",
    ["a" * 101, "", "tab\there", "Jos\u00e9".encode()],
    ids=["too-long", "empty", "control-character", "non-ascii"],
)
def test_invalid_actor_returns_422_and_changes_nothing(client, actor):
    response = client.post(FLAGS, json=NEW_FLAG, headers={"X-Actor": actor})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "header.X-Actor"
    assert client.get(FLAG).status_code == 404
    assert history(client) == []


def test_actor_header_is_validated_on_reads_too(client):
    assert client.get(FLAGS, headers={"X-Actor": ""}).status_code == 422


def test_api_key_is_checked_before_the_actor_header(client):
    del client.headers["X-API-Key"]

    assert client.post(FLAGS, json=NEW_FLAG, headers={"X-Actor": ""}).status_code == 401


def test_rejected_duplicate_create_writes_no_event(client):
    client.post(FLAGS, json=NEW_FLAG)

    response = client.post(FLAGS, json={"key": "new-checkout", "name": "Again"}, headers=ALICE)

    assert response.status_code == 409
    assert history(client) == [("flag.created", None, CREATED_DETAILS)]


def test_changes_that_fail_write_no_event(client):
    client.post(FLAGS, json=NEW_FLAG)

    assert client.delete(f"{FLAG}/overrides/nobody").status_code == 404
    assert client.patch(f"{FLAGS}/missing", json={"enabled": True}).status_code == 404
    assert client.delete(f"{FLAGS}/missing").status_code == 404

    assert history(client) == [("flag.created", None, CREATED_DETAILS)]
    assert client.get(f"{FLAGS}/missing/audit").json()["total"] == 0


def test_a_failed_audit_write_rolls_back_the_change(settings, clean_database):
    app = create_app(settings)
    # Skips header validation, so the audit INSERT itself fails (actor too long for the column).
    app.dependency_overrides[get_actor] = lambda: "a" * 101

    with TestClient(
        app, headers={"X-API-Key": settings.api_key}, raise_server_exceptions=False
    ) as client:
        response = client.post(FLAGS, json=NEW_FLAG)

        assert response.status_code == 500
        assert client.get(FLAG).status_code == 404
        assert client.get(AUDIT).json()["total"] == 0


def test_history_is_kept_after_the_flag_is_deleted(client, make_flag):
    make_flag("new-checkout")
    client.delete(FLAG)

    response = client.get(AUDIT)

    assert client.get(FLAG).status_code == 404
    assert response.status_code == 200
    assert [event["action"] for event in response.json()["items"]] == [
        "flag.deleted",
        "flag.created",
    ]
    # History belongs to the key, so a flag re-created with it continues the same history.
    make_flag("new-checkout")
    assert client.get(AUDIT).json()["total"] == 3


def test_history_is_paginated_newest_first(client, make_flag):
    make_flag("new-checkout")
    for percentage in (10, 20, 30):
        client.patch(FLAG, json={"rollout_percentage": percentage})

    page = client.get(AUDIT, params={"limit": 2}).json()
    rest = client.get(AUDIT, params={"limit": 2, "offset": 2}).json()

    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 0)
    assert [event["details"] for event in page["items"]] == [
        {"rollout_percentage": 30},
        {"rollout_percentage": 20},
    ]
    assert [event["action"] for event in rest["items"]] == ["flag.updated", "flag.created"]
    assert rest["items"][0]["details"] == {"rollout_percentage": 10}
    times = [datetime.fromisoformat(event["created_at"]) for event in page["items"] + rest["items"]]
    assert times == sorted(times, reverse=True)


def test_key_without_history_returns_an_empty_list(client):
    response = client.get(f"{FLAGS}/never-existed/audit")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_audit_needs_the_api_key(client):
    del client.headers["X-API-Key"]

    response = client.get(AUDIT)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_audit_rejects_bad_pagination(client, params):
    assert client.get(AUDIT, params=params).status_code == 422


def test_audit_rejects_an_invalid_key(client):
    assert client.get(f"{FLAGS}/Not-A-Key/audit").status_code == 422
