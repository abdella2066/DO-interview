from app.evaluation import Evaluation, FlagSnapshot, Reason, evaluate, rollout_bucket

USERS = [f"user-{i}" for i in range(10_000)]


def users_in_rollout(percentage, key="new-checkout"):
    snapshot = FlagSnapshot(key=key, enabled=True, rollout_percentage=percentage)
    return {user for user in USERS if evaluate(snapshot, user).enabled}


def test_user_without_override_gets_the_global_state():
    enabled_flag = FlagSnapshot(key="new-checkout", enabled=True)
    disabled_flag = FlagSnapshot(key="new-checkout", enabled=False)

    assert evaluate(enabled_flag, "user-1") == Evaluation(enabled=True, reason=Reason.GLOBAL)
    assert evaluate(disabled_flag, "user-1") == Evaluation(enabled=False, reason=Reason.GLOBAL)


def test_override_enables_a_globally_disabled_flag_for_that_user_only():
    snapshot = FlagSnapshot(key="new-checkout", enabled=False, overrides={"beta-tester": True})

    assert evaluate(snapshot, "beta-tester") == Evaluation(True, Reason.USER_OVERRIDE)
    assert evaluate(snapshot, "someone-else") == Evaluation(False, Reason.GLOBAL)


def test_override_disables_a_globally_enabled_flag_for_that_user_only():
    snapshot = FlagSnapshot(key="new-checkout", enabled=True, overrides={"opted-out": False})

    assert evaluate(snapshot, "opted-out") == Evaluation(False, Reason.USER_OVERRIDE)
    assert evaluate(snapshot, "someone-else") == Evaluation(True, Reason.GLOBAL)


def test_user_ids_are_case_sensitive():
    snapshot = FlagSnapshot(key="new-checkout", enabled=False, overrides={"Alice": True})

    assert evaluate(snapshot, "alice") == Evaluation(False, Reason.GLOBAL)


def test_rollout_is_deterministic():
    snapshot = FlagSnapshot(key="new-checkout", enabled=True, rollout_percentage=50)

    first = [evaluate(snapshot, user) for user in USERS[:100]]
    second = [evaluate(snapshot, user) for user in USERS[:100]]

    assert first == second
    assert {result.reason for result in first} == {Reason.ROLLOUT}
    # Pinned: changing the hash would move users in or out of every running rollout.
    assert rollout_bucket("new-checkout", "user-1") == 48


def test_raising_the_percentage_only_adds_users():
    at_10 = users_in_rollout(10)
    at_50 = users_in_rollout(50)

    assert at_10 < at_50


def test_rollout_reaches_about_the_requested_share_of_users():
    share = len(users_in_rollout(25)) / len(USERS)

    assert 0.23 <= share <= 0.27


def test_each_flag_picks_its_own_users():
    checkout = users_in_rollout(10, key="new-checkout")
    dark_mode = users_in_rollout(10, key="dark-mode")

    # Independent 10% samples share about 10% of their users, not all of them.
    assert 0.05 <= len(checkout & dark_mode) / len(checkout) <= 0.15


def test_zero_percent_on_an_enabled_flag_reaches_nobody():
    snapshot = FlagSnapshot(key="new-checkout", enabled=True, rollout_percentage=0)

    assert {evaluate(snapshot, user) for user in USERS} == {Evaluation(False, Reason.ROLLOUT)}


def test_disabled_flag_ignores_the_rollout():
    snapshot = FlagSnapshot(key="new-checkout", enabled=False, rollout_percentage=50)

    assert {evaluate(snapshot, user) for user in USERS} == {Evaluation(False, Reason.GLOBAL)}


def test_override_beats_the_rollout():
    inside = next(user for user in USERS if rollout_bucket("new-checkout", user) < 50)
    half = FlagSnapshot(
        key="new-checkout", enabled=True, rollout_percentage=50, overrides={inside: False}
    )
    nobody = FlagSnapshot(
        key="new-checkout", enabled=True, rollout_percentage=0, overrides={"beta-tester": True}
    )

    assert evaluate(half, inside) == Evaluation(False, Reason.USER_OVERRIDE)
    assert evaluate(nobody, "beta-tester") == Evaluation(True, Reason.USER_OVERRIDE)


def test_snapshot_survives_a_json_round_trip():
    snapshot = FlagSnapshot(
        key="new-checkout",
        enabled=True,
        rollout_percentage=25,
        overrides={"a": False, "b": True},
    )

    assert FlagSnapshot.from_json(snapshot.to_json()) == snapshot
