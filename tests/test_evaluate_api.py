import pytest

FLAG = "/api/v1/flags/new-checkout"


def evaluate(client, user_id):
    return client.get(f"{FLAG}/evaluate", params={"user_id": user_id})


def test_user_without_override_gets_the_global_state(client, make_flag):
    make_flag("new-checkout", enabled=True)

    response = evaluate(client, "user-1")

    assert response.status_code == 200
    assert response.json() == {
        "flag_key": "new-checkout",
        "user_id": "user-1",
        "enabled": True,
        "reason": "GLOBAL",
    }


def test_override_enables_a_disabled_flag_for_one_user(client, make_flag):
    make_flag("new-checkout", enabled=False)
    client.put(f"{FLAG}/overrides/beta-tester", json={"enabled": True})

    tester = evaluate(client, "beta-tester").json()
    other = evaluate(client, "someone-else").json()

    assert (tester["enabled"], tester["reason"]) == (True, "USER_OVERRIDE")
    assert (other["enabled"], other["reason"]) == (False, "GLOBAL")


def test_override_disables_an_enabled_flag_for_one_user(client, make_flag):
    make_flag("new-checkout", enabled=True)
    client.put(f"{FLAG}/overrides/opted-out", json={"enabled": False})

    opted_out = evaluate(client, "opted-out").json()

    assert (opted_out["enabled"], opted_out["reason"]) == (False, "USER_OVERRIDE")
    assert evaluate(client, "someone-else").json()["enabled"] is True


def test_unknown_flag_returns_404(client):
    response = client.get("/api/v1/flags/missing/evaluate", params={"user_id": "user-1"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FLAG_NOT_FOUND"


@pytest.mark.parametrize(
    "params", [{}, {"user_id": ""}, {"user_id": "has space"}, {"user_id": "u" * 129}]
)
def test_missing_or_invalid_user_id_returns_422(client, make_flag, params):
    make_flag("new-checkout")

    response = client.get(f"{FLAG}/evaluate", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_repeat_evaluations_are_served_from_the_cache(client, make_flag):
    make_flag("new-checkout")

    assert evaluate(client, "user-1").headers["x-cache"] == "MISS"
    assert evaluate(client, "user-1").headers["x-cache"] == "HIT"
    # The cached snapshot is per flag, so other users hit it too.
    assert evaluate(client, "user-2").headers["x-cache"] == "HIT"


def test_global_toggle_invalidates_the_cache(client, make_flag):
    make_flag("new-checkout", enabled=False)
    evaluate(client, "user-1")

    client.patch(FLAG, json={"enabled": True})
    response = evaluate(client, "user-1")

    assert response.headers["x-cache"] == "MISS"
    assert response.json()["enabled"] is True


def test_setting_an_override_invalidates_the_cache(client, make_flag):
    make_flag("new-checkout", enabled=False)
    evaluate(client, "user-1")

    client.put(f"{FLAG}/overrides/user-1", json={"enabled": True})
    response = evaluate(client, "user-1")

    assert response.headers["x-cache"] == "MISS"
    assert (response.json()["enabled"], response.json()["reason"]) == (True, "USER_OVERRIDE")


def test_removing_an_override_falls_back_to_the_global_state(client, make_flag):
    make_flag("new-checkout", enabled=True)
    client.put(f"{FLAG}/overrides/user-1", json={"enabled": False})
    assert evaluate(client, "user-1").json()["enabled"] is False

    client.delete(f"{FLAG}/overrides/user-1")
    response = evaluate(client, "user-1")

    assert response.headers["x-cache"] == "MISS"
    assert (response.json()["enabled"], response.json()["reason"]) == (True, "GLOBAL")


def test_deleted_flag_is_not_served_from_the_cache(client, make_flag):
    make_flag("new-checkout")
    evaluate(client, "user-1")

    client.delete(FLAG)

    assert evaluate(client, "user-1").status_code == 404


def test_recreated_flag_does_not_inherit_stale_state(client, make_flag):
    make_flag("new-checkout", enabled=True)
    client.put(f"{FLAG}/overrides/user-1", json={"enabled": False})
    evaluate(client, "user-1")

    client.delete(FLAG)
    make_flag("new-checkout", enabled=False)
    response = evaluate(client, "user-1").json()

    assert (response["enabled"], response["reason"]) == (False, "GLOBAL")
