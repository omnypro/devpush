import asyncio
from types import SimpleNamespace

import pytest

from services.runner_restart import RESTART_POLICY, keep_running_after_reboot
from workers.tasks import deployment as tasks


class FakeDocker:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def _query_json(self, path, method="GET", **kwargs):
        self.calls.append((path, method, kwargs))
        if self.error:
            raise self.error
        return {}


def keep(docker, container_id="abc123"):
    return asyncio.run(keep_running_after_reboot(docker, container_id))


def test_updates_the_container_restart_policy():
    docker = FakeDocker()

    assert keep(docker) is True

    assert docker.calls == [
        (
            "containers/abc123/update",
            "POST",
            {"data": {"RestartPolicy": {"Name": "unless-stopped"}}},
        )
    ]


def test_the_policy_restarts_after_a_reboot_but_not_after_a_deliberate_stop():
    assert RESTART_POLICY == {"Name": "unless-stopped"}


@pytest.mark.parametrize("container_id", [None, ""])
def test_does_nothing_without_a_container(container_id):
    docker = FakeDocker()

    assert keep(docker, container_id) is False
    assert docker.calls == []


def test_a_failed_update_is_reported_not_raised():
    docker = FakeDocker(error=RuntimeError("proxy refused"))

    assert keep(docker) is False


class FakeDockerClient(FakeDocker):
    instances = []

    def __init__(self, url=None):
        super().__init__()
        self.url = url
        FakeDockerClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


@pytest.fixture
def docker_client(monkeypatch):
    FakeDockerClient.instances = []
    monkeypatch.setattr(tasks.aiodocker, "Docker", FakeDockerClient)
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(docker_host="tcp://proxy:2375")
    )
    return FakeDockerClient


def test_a_finished_deployment_keeps_its_runner_across_reboots(docker_client):
    deployment = SimpleNamespace(id="d1", container_id="c9")

    asyncio.run(tasks._keep_runner_across_reboots(deployment))

    (client,) = docker_client.instances
    assert client.url == "tcp://proxy:2375"
    assert client.calls[0][0] == "containers/c9/update"


def test_a_deployment_without_a_container_opens_no_docker_client(docker_client):
    asyncio.run(
        tasks._keep_runner_across_reboots(SimpleNamespace(id="d1", container_id=None))
    )

    assert docker_client.instances == []


def test_a_docker_failure_never_fails_the_deployment(docker_client, monkeypatch):
    class Broken(FakeDockerClient):
        async def __aenter__(self):
            raise OSError("docker unreachable")

    monkeypatch.setattr(tasks.aiodocker, "Docker", Broken)

    asyncio.run(
        tasks._keep_runner_across_reboots(SimpleNamespace(id="d1", container_id="c9"))
    )
