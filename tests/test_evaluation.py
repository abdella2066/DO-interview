from app.evaluation import Evaluation, FlagSnapshot, Reason, evaluate


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


def test_snapshot_survives_a_json_round_trip():
    snapshot = FlagSnapshot(key="new-checkout", enabled=True, overrides={"a": False, "b": True})

    assert FlagSnapshot.from_json(snapshot.to_json()) == snapshot
