import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from services.build_gate import (
    admit_start,
    container_started_at_key,
    timeout_started_at,
)


class Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def scalar_one(self):
        return self.value

    def one_or_none(self):
        return self.value


class FakeLockConn:
    def __init__(self, got=True):
        self.got = got
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return Result(self.got)


class FakeDB:
    """Answers the two queries the gate issues, told apart by the statement text."""

    def __init__(self, starting=0, conclusion=None, missing=False):
        self.starting = starting
        self.row = None if missing else ("d1", conclusion)
        self.statements = []

    async def execute(self, statement):
        text = str(statement).lower()
        self.statements.append(text)
        if "count(" in text:
            return Result(self.starting)
        return Result(self.row)


def admit(conn=None, db=None, limit=2):
    return asyncio.run(
        admit_start(conn or FakeLockConn(), db or FakeDB(), "d1", limit)
    )


def test_starts_when_nothing_is_building():
    assert admit(db=FakeDB(starting=0)) == "start"


def test_starts_while_under_the_limit():
    assert admit(db=FakeDB(starting=1), limit=2) == "start"


def test_waits_at_the_limit():
    assert admit(db=FakeDB(starting=2), limit=2) == "wait"


def test_waits_over_the_limit():
    assert admit(db=FakeDB(starting=5), limit=2) == "wait"


def test_a_limit_of_one_runs_builds_one_at_a_time():
    assert admit(db=FakeDB(starting=0), limit=1) == "start"
    assert admit(db=FakeDB(starting=1), limit=1) == "wait"


def test_waits_when_another_start_holds_the_lock():
    db = FakeDB(starting=0)

    assert admit(conn=FakeLockConn(got=False), db=db) == "wait"
    assert db.statements == []


def test_takes_a_transaction_scoped_advisory_lock_without_blocking():
    conn = FakeLockConn()

    admit(conn=conn)

    statement, _ = conn.statements[0]
    assert "pg_try_advisory_xact_lock" in statement


def test_skips_a_canceled_deployment():
    assert admit(db=FakeDB(starting=0, conclusion="canceled")) == "skip"


def test_skips_a_deployment_that_no_longer_exists():
    assert admit(db=FakeDB(missing=True)) == "skip"


def test_a_canceled_deployment_is_skipped_even_when_the_box_is_full():
    assert admit(db=FakeDB(starting=9, conclusion="canceled"), limit=2) == "skip"


def test_counts_only_deployments_that_are_starting_a_container():
    db = FakeDB(starting=0)

    admit(db=db)

    count = next(text for text in db.statements if "count(" in text)
    assert "status" in count
    assert "container_status" in count


def test_container_started_key_is_per_deployment():
    assert container_started_at_key("abc") == "deployment:abc:container_started_at"


def test_timeout_runs_from_created_at_without_a_recorded_start():
    created = datetime(2026, 10, 13, 5, 0, 0)

    assert timeout_started_at(created, None) == created.replace(tzinfo=timezone.utc)


def test_timeout_runs_from_the_recorded_container_start():
    created = datetime(2026, 10, 13, 5, 0, 0)
    started = created.replace(tzinfo=timezone.utc) + timedelta(seconds=120)

    assert timeout_started_at(created, started.isoformat()) == started


def test_timeout_accepts_the_start_as_bytes():
    created = datetime(2026, 10, 13, 5, 0, 0)
    started = created.replace(tzinfo=timezone.utc) + timedelta(seconds=45)

    assert timeout_started_at(created, started.isoformat().encode()) == started


@pytest.mark.parametrize("junk", ["", "not a date", b"\xff"])
def test_timeout_falls_back_to_created_at_for_an_unreadable_start(junk):
    created = datetime(2026, 10, 13, 5, 0, 0)

    assert timeout_started_at(created, junk) == created.replace(tzinfo=timezone.utc)


def test_timeout_treats_a_naive_created_at_as_utc():
    created = datetime(2026, 10, 13, 5, 0, 0)

    assert timeout_started_at(created, None).tzinfo is timezone.utc


def test_timeout_keeps_an_aware_created_at():
    created = datetime(2026, 10, 13, 5, 0, 0, tzinfo=timezone.utc)

    assert timeout_started_at(created, None) == created
