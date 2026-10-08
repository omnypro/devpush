import asyncio
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import models
from models import Deployment, Project
from services import deployment as deployment_module
from services.deployment import DeploymentService

PROD = {"id": "prod", "slug": "production", "branch": "", "status": "active"}
STAGING = {"id": "a1b2c3d4", "slug": "staging", "branch": "main", "status": "active"}
GONE = {"id": "dead0000", "slug": "gone", "branch": "x", "status": "deleted"}


class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, name, fields=None):
        self.events.append(fields)


@pytest.fixture(autouse=True)
def stub_registry(monkeypatch):
    state = SimpleNamespace(
        runners=[{"slug": "python", "enabled": True, "image": "runner:python"}]
    )

    class FakeRegistry:
        def __init__(self, *_args, **_kwargs):
            self.state = state

    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(models, "get_fernet", lambda: fernet)
    monkeypatch.setattr(deployment_module, "RegistryService", FakeRegistry)
    monkeypatch.setattr(
        deployment_module, "get_settings", lambda: SimpleNamespace(data_dir="/nonexistent")
    )


def make_project():
    return Project(
        id="p1",
        name="app",
        slug="app",
        config={"runner": "python"},
        environments=[STAGING, PROD, GONE],
        env_vars=[
            {"key": "A", "value": "base"},
            {"key": "A", "value": "prod-a", "environment": "production"},
            {"key": "B", "value": "staging-b", "environment": "staging"},
        ],
    )


def make_source(**kwargs):
    defaults = dict(
        environment_id=STAGING["id"],
        branch="main",
        commit_sha="abc123",
        commit_meta={"author": "bryan", "message": "msg", "date": "2026-01-01T00:00:00+00:00"},
        conclusion="succeeded",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def run(coro):
    return asyncio.run(coro)


def test_promote_creates_prod_deployment_with_prod_env_vars():
    project, db, redis = make_project(), FakeDB(), FakeRedis()
    new = run(DeploymentService().promote(make_source(), project, db, redis))
    assert isinstance(new, Deployment)
    assert new.environment_id == "prod"
    assert new.commit_sha == "abc123"
    assert new.branch == "main"
    assert new.commit_meta["author"] == "bryan"
    assert new.commit_meta["message"] == "msg"
    assert new.commit_meta["date"] == "2026-01-01T00:00:00+00:00"
    assert {v["key"]: v["value"] for v in new.env_vars} == {"A": "prod-a"}
    assert redis.events[0]["event_type"] == "deployment_creation"


def test_promote_rejects_prod_source():
    with pytest.raises(ValueError, match="already in production"):
        run(
            DeploymentService().promote(
                make_source(environment_id="prod"), make_project(), FakeDB(), FakeRedis()
            )
        )


def test_promote_rejects_unsuccessful_source():
    with pytest.raises(ValueError, match="Only successful"):
        run(
            DeploymentService().promote(
                make_source(conclusion="failed"), make_project(), FakeDB(), FakeRedis()
            )
        )


def test_promote_requires_production_environment():
    project = make_project()
    project.environments = [STAGING]
    with pytest.raises(ValueError, match="Production environment not found"):
        run(DeploymentService().promote(make_source(), project, FakeDB(), FakeRedis()))


def commit():
    return {"sha": "abc123", "commit": {"message": "m"}}


def test_create_without_environment_id_resolves_by_branch():
    new = run(
        DeploymentService().create(
            make_project(), "main", commit(), FakeDB(), FakeRedis()
        )
    )
    assert new.environment_id == STAGING["id"]
    assert {v["key"]: v["value"] for v in new.env_vars} == {"A": "base", "B": "staging-b"}


def test_create_with_unknown_or_inactive_environment_id_fails():
    for env_id in ("nope", GONE["id"]):
        with pytest.raises(ValueError, match="Environment not found"):
            run(
                DeploymentService().create(
                    make_project(), "main", commit(), FakeDB(), FakeRedis(),
                    environment_id=env_id,
                )
            )


ALIAS_SETTINGS = SimpleNamespace(deploy_domain="stage.respro.dev", url_scheme="https")
LEGACY_PROD = {"id": "prod", "slug": "production", "branch": "main", "status": "active"}


def alias_domains(environment_id, branch, environments, slug="cenitlaw"):
    project = Project(id="p2", name=slug, slug=slug, environments=environments)
    deployment = Deployment(
        project=project,
        environment_id=environment_id,
        branch=branch,
        commit_sha="abc123",
        commit_meta={},
    )
    return DeploymentService().get_alias_domains(deployment, ALIAS_SETTINGS)


def test_alias_domains_legacy_prod_with_branch_pins_live_names():
    assert alias_domains("prod", "main", [LEGACY_PROD, STAGING]) == {
        "branch_subdomain": "cenitlaw-branch-main",
        "branch_domain": "cenitlaw-branch-main.stage.respro.dev",
        "branch_url": "https://cenitlaw-branch-main.stage.respro.dev",
        "environment_subdomain": "cenitlaw",
        "environment_domain": "cenitlaw.stage.respro.dev",
        "environment_url": "https://cenitlaw.stage.respro.dev",
        "environment_id_subdomain": "cenitlaw-env-id-prod",
        "environment_id_domain": "cenitlaw-env-id-prod.stage.respro.dev",
        "environment_id_url": "https://cenitlaw-env-id-prod.stage.respro.dev",
    }


def test_alias_domains_staging_pins_live_names():
    assert alias_domains(STAGING["id"], "main", [LEGACY_PROD, STAGING]) == {
        "branch_subdomain": "cenitlaw-branch-main",
        "branch_domain": "cenitlaw-branch-main.stage.respro.dev",
        "branch_url": "https://cenitlaw-branch-main.stage.respro.dev",
        "environment_subdomain": "cenitlaw-env-staging",
        "environment_domain": "cenitlaw-env-staging.stage.respro.dev",
        "environment_url": "https://cenitlaw-env-staging.stage.respro.dev",
        "environment_id_subdomain": "cenitlaw-env-id-a1b2c3d4",
        "environment_id_domain": "cenitlaw-env-id-a1b2c3d4.stage.respro.dev",
        "environment_id_url": "https://cenitlaw-env-id-a1b2c3d4.stage.respro.dev",
    }


def test_alias_domains_promote_only_prod_has_no_branch_alias():
    assert alias_domains("prod", "main", [PROD, STAGING]) == {
        "environment_subdomain": "cenitlaw",
        "environment_domain": "cenitlaw.stage.respro.dev",
        "environment_url": "https://cenitlaw.stage.respro.dev",
        "environment_id_subdomain": "cenitlaw-env-id-prod",
        "environment_id_domain": "cenitlaw-env-id-prod.stage.respro.dev",
        "environment_id_url": "https://cenitlaw-env-id-prod.stage.respro.dev",
    }
