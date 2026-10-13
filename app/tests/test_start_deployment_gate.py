import asyncio
from types import SimpleNamespace

import pytest

from workers.tasks import deployment as tasks


class FakeEngine:
    def __init__(self, events):
        self.events = events

    def begin(self):
        events = self.events

        class Transaction:
            async def __aenter__(self):
                events.append("lock transaction opened")
                return "lock-conn"

            async def __aexit__(self, *exc):
                events.append("lock transaction closed")

        return Transaction()


class FakeSession:
    async def __aenter__(self):
        return "db"

    async def __aexit__(self, *exc):
        return None


class FakeQueue:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))


@pytest.fixture
def wired(monkeypatch):
    events = []
    queue = FakeQueue()
    settings = SimpleNamespace(max_concurrent_builds=2, build_wait_seconds=10)
    calls = {}

    async def fake_start(ctx, deployment_id):
        events.append("started")

    def verdict(value):
        async def admit(lock_conn, db, deployment_id, limit):
            calls["admit"] = (lock_conn, db, deployment_id, limit)
            return value

        monkeypatch.setattr(tasks, "admit_start", admit)

    monkeypatch.setattr(tasks, "engine", FakeEngine(events))
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks, "_start_deployment", fake_start)

    def run():
        asyncio.run(tasks.start_deployment({"redis": queue}, "d1"))

    return SimpleNamespace(
        events=events, queue=queue, settings=settings, calls=calls, verdict=verdict, run=run
    )


def test_starts_the_deployment_while_holding_the_lock(wired):
    wired.verdict("start")

    wired.run()

    assert wired.events == [
        "lock transaction opened",
        "started",
        "lock transaction closed",
    ]
    assert wired.queue.jobs == []


def test_a_waiting_deployment_is_queued_again_after_the_wait(wired):
    wired.verdict("wait")

    wired.run()

    assert "started" not in wired.events
    assert wired.queue.jobs == [("start_deployment", ("d1",), {"_defer_by": 10})]


def test_the_wait_follows_the_setting(wired):
    wired.settings.build_wait_seconds = 25
    wired.verdict("wait")

    wired.run()

    assert wired.queue.jobs[0][2] == {"_defer_by": 25}


def test_a_skipped_deployment_starts_nothing_and_queues_nothing(wired):
    wired.verdict("skip")

    wired.run()

    assert "started" not in wired.events
    assert wired.queue.jobs == []


def test_the_gate_gets_the_configured_limit(wired):
    wired.settings.max_concurrent_builds = 3
    wired.verdict("start")

    wired.run()

    assert wired.calls["admit"] == ("lock-conn", "db", "d1", 3)


def test_the_lock_is_released_when_the_start_fails(wired, monkeypatch):
    async def boom(ctx, deployment_id):
        raise RuntimeError("no container")

    wired.verdict("start")
    monkeypatch.setattr(tasks, "_start_deployment", boom)

    with pytest.raises(RuntimeError):
        wired.run()

    assert wired.events[-1] == "lock transaction closed"
