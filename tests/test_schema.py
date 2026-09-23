import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_rows_inserted_without_a_rollout_reach_everyone(database_engine, clean_database):
    # The previous release, still serving during a deploy, inserts flags without this column.
    with database_engine.begin() as connection:
        connection.execute(text("INSERT INTO flags (key, name) VALUES ('legacy', 'Legacy')"))
        rollout = connection.scalar(text("SELECT rollout_percentage FROM flags"))

    assert rollout == 100


@pytest.mark.parametrize("percentage", [-1, 101])
def test_database_rejects_out_of_range_rollouts(database_engine, clean_database, percentage):
    insert = text("INSERT INTO flags (key, name, rollout_percentage) VALUES ('bad', 'Bad', :p)")

    with (
        pytest.raises(IntegrityError, match="flags_rollout_percentage_check"),
        database_engine.begin() as connection,
    ):
        connection.execute(insert, {"p": percentage})
