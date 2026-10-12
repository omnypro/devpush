import asyncio
from types import SimpleNamespace

import pytest
import yaml

from models import Alias, Domain, Project
from services.deployment import DeploymentService
from utils.alias import environment_id_subdomain, environment_subdomain

SLUG = "cenitlaw-com-marketing"
LEGACY_PROD = {"id": "prod", "slug": "production", "branch": "main", "status": "active"}
PROD = {"id": "prod", "slug": "production", "branch": "", "status": "active"}
STAGING = {"id": "a1b2c3d4", "slug": "staging", "branch": "staging", "status": "active"}
LIVE_SLUGS = [
    "cenitlaw-com-marketing",
    "certezzadata-com-marketing",
    "morninglawgroup-com-marketing",
    "resolutionprocessing-com-marketing",
]

BEFORE = """http:
  routers:
    router-alias-1:
      rule: Host(`cenitlaw-com-marketing.stage.respro.dev`)
      service: deployment-P2@docker
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: le
    router-alias-2:
      rule: Host(`cenitlaw-com-marketing-env-id-prod.stage.respro.dev`)
      service: deployment-P2@docker
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: le
    router-alias-3:
      rule: Host(`cenitlaw-com-marketing-branch-main.stage.respro.dev`)
      service: deployment-P2@docker
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: le
    router-alias-4:
      rule: Host(`cenitlaw-com-marketing-env-staging.stage.respro.dev`)
      service: deployment-S@docker
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: le
    router-alias-5:
      rule: Host(`cenitlaw-com-marketing-env-id-a1b2c3d4.stage.respro.dev`)
      service: deployment-S@docker
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: le
    router-domain-1:
      rule: Host(`cenitlaw.com`)
      service: deployment-P2@docker
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: lehttp
    router-redirect-2:
      rule: Host(`www.cenitlaw.com`)
      service: noop@internal
      middlewares:
      - redirect-2
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: lehttp
    router-domain-3:
      rule: Host(`staging.cenitlaw.com`)
      service: deployment-S@docker
      entryPoints:
      - web
      - websecure
      tls:
        certResolver: lehttp
  middlewares:
    redirect-2:
      redirectRegex:
        regex: ^https?://www.cenitlaw.com/(.*)
        replacement: https://cenitlaw-com-marketing-env-id-prod.stage.respro.dev/$1
        permanent: true
"""


class Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    def __init__(self, aliases, domains, succeeded):
        self.aliases = aliases
        self.domains = domains
        self.succeeded = succeeded
        self.commits = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        if entity is Domain:
            return Result(d for d in self.domains if d.status == "active")
        if "subdomain_1" in params:
            return Result(a for a in self.aliases if a.subdomain == params["subdomain_1"])
        included = self.succeeded | set(params.get("id_1") or [])
        return Result(a for a in self.aliases if a.deployment_id in included)

    def add(self, obj):
        self.aliases.append(obj)

    async def commit(self):
        self.commits.append(holders(self))


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, name, fields=None):
        self.events.append(fields)


def holders(db):
    return {a.subdomain: (a.deployment_id, a.previous_deployment_id) for a in db.aliases}


def make_db(env=("P2", "P1"), id_holder="P2", with_id_alias=True):
    aliases = [
        Alias(id=1, subdomain=SLUG, type="environment", value="prod",
              deployment_id=env[0], previous_deployment_id=env[1]),
        Alias(id=3, subdomain=f"{SLUG}-branch-main", type="branch", value="main",
              deployment_id="P2"),
        Alias(id=4, subdomain=f"{SLUG}-env-staging", type="environment",
              value="a1b2c3d4", deployment_id="S"),
        Alias(id=5, subdomain=f"{SLUG}-env-id-a1b2c3d4", type="environment_id",
              value="a1b2c3d4", deployment_id="S"),
    ]
    if with_id_alias:
        aliases.insert(1, Alias(id=2, subdomain=f"{SLUG}-env-id-prod",
                                type="environment_id", value="prod",
                                deployment_id=id_holder))
    domains = [
        Domain(id=1, project_id="p1", hostname="cenitlaw.com", type="route",
               status="active", environment_id="prod"),
        Domain(id=2, project_id="p1", hostname="www.cenitlaw.com", type="301",
               status="active", environment_id="prod"),
        Domain(id=3, project_id="p1", hostname="staging.cenitlaw.com", type="route",
               status="active", environment_id="a1b2c3d4"),
        Domain(id=4, project_id="p1", hostname="pending.cenitlaw.com", type="route",
               status="pending", environment_id="prod"),
    ]
    return FakeDB(aliases, domains, {"P1", "P2", "S"})


def make_project(prod=LEGACY_PROD):
    return Project(id="p1", name="cenitlaw.com", slug=SLUG, environments=[prod, STAGING])


def settings(tmp_path):
    return SimpleNamespace(
        deploy_domain="stage.respro.dev", url_scheme="https", traefik_dir=str(tmp_path)
    )


def rollback(db, tmp_path, prod=LEGACY_PROD):
    asyncio.run(
        DeploymentService().rollback(
            prod, make_project(prod), db, FakeRedis(), settings(tmp_path)
        )
    )


def render(db, tmp_path, prod=LEGACY_PROD):
    asyncio.run(
        DeploymentService().update_traefik_config(
            make_project(prod), db, settings(tmp_path)
        )
    )
    return (tmp_path / "project_p1.yml").read_text()


def routers(tmp_path):
    return yaml.safe_load((tmp_path / "project_p1.yml").read_text())["http"]


@pytest.mark.parametrize("slug", LIVE_SLUGS)
def test_live_prod_alias_names_are_unchanged(slug):
    assert environment_subdomain(slug, LEGACY_PROD) == slug
    assert environment_id_subdomain(slug, "prod") == f"{slug}-env-id-prod"


def test_traefik_output_for_unchanged_state_is_pinned(tmp_path):
    assert render(make_db(), tmp_path) == BEFORE


def test_rollback_moves_custom_domain_with_production_alias(tmp_path):
    db = make_db()
    rollback(db, tmp_path)
    assert holders(db)[SLUG] == ("P1", "P2")
    assert holders(db)[f"{SLUG}-env-id-prod"] == ("P1", "P2")
    http = routers(tmp_path)
    assert http["routers"]["router-domain-1"]["service"] == "deployment-P1@docker"


def test_rollback_changes_only_the_production_routers(tmp_path):
    before = yaml.safe_load(BEFORE)["http"]
    db = make_db()
    rollback(db, tmp_path)
    after = routers(tmp_path)
    assert after["middlewares"] == before["middlewares"]
    assert after["routers"].keys() == before["routers"].keys()
    changed = {
        key for key in before["routers"] if before["routers"][key] != after["routers"][key]
    }
    assert changed == {"router-alias-1", "router-alias-2", "router-domain-1"}
    for key in changed:
        assert after["routers"][key] == {
            **before["routers"][key],
            "service": "deployment-P1@docker",
        }


def test_rollback_keeps_branch_alias_staging_and_redirects(tmp_path):
    db = make_db()
    rollback(db, tmp_path)
    assert holders(db)[f"{SLUG}-branch-main"] == ("P2", None)
    assert holders(db)[f"{SLUG}-env-staging"] == ("S", None)
    assert holders(db)[f"{SLUG}-env-id-a1b2c3d4"] == ("S", None)
    http = routers(tmp_path)
    assert http["routers"]["router-domain-3"]["service"] == "deployment-S@docker"
    assert http["middlewares"]["redirect-2"]["redirectRegex"]["replacement"] == (
        "https://cenitlaw-com-marketing-env-id-prod.stage.respro.dev/$1"
    )
    assert "pending.cenitlaw.com" not in (tmp_path / "project_p1.yml").read_text()


def test_roll_forward_restores_both_aliases(tmp_path):
    db = make_db()
    rollback(db, tmp_path)
    rollback(db, tmp_path)
    assert holders(db)[SLUG] == ("P2", "P1")
    assert holders(db)[f"{SLUG}-env-id-prod"] == ("P2", "P1")
    assert render(db, tmp_path) == BEFORE


def test_rollback_commits_both_aliases_together(tmp_path):
    db = make_db()
    rollback(db, tmp_path)
    assert len(db.commits) == 1
    assert db.commits[0][SLUG][0] == db.commits[0][f"{SLUG}-env-id-prod"][0] == "P1"


def test_rollback_heals_a_diverged_environment_id_alias(tmp_path):
    db = make_db(env=("P1", "P2"), id_holder="P2")
    rollback(db, tmp_path)
    assert holders(db)[SLUG] == ("P2", "P1")
    assert holders(db)[f"{SLUG}-env-id-prod"] == ("P2", None)
    rollback(db, tmp_path)
    assert holders(db)[SLUG] == ("P1", "P2")
    assert holders(db)[f"{SLUG}-env-id-prod"] == ("P1", "P2")
    assert routers(tmp_path)["routers"]["router-domain-1"]["service"] == (
        "deployment-P1@docker"
    )


def test_rollback_without_environment_id_alias_still_swaps(tmp_path):
    db = make_db(with_id_alias=False)
    rollback(db, tmp_path)
    assert holders(db)[SLUG] == ("P1", "P2")
    assert "router-domain-1" not in routers(tmp_path)["routers"]


def test_rollback_without_previous_changes_nothing(tmp_path):
    db = make_db(env=("P2", None))
    with pytest.raises(ValueError, match="No previous deployment"):
        rollback(db, tmp_path)
    assert db.commits == []
    assert holders(db)[f"{SLUG}-env-id-prod"] == ("P2", None)


def test_promote_moves_custom_domain_and_rollback_moves_it_back(tmp_path):
    db = make_db()
    project = make_project(PROD)
    deployment = SimpleNamespace(
        id="N", project=project, environment_id="prod", branch="main"
    )
    service = DeploymentService()
    asyncio.run(service.setup_aliases(deployment, db, settings(tmp_path)))
    asyncio.run(
        service.update_traefik_config(
            project, db, settings(tmp_path), include_deployment_ids={"N"}
        )
    )
    assert holders(db)[SLUG] == ("N", "P2")
    assert holders(db)[f"{SLUG}-env-id-prod"] == ("N", None)
    assert holders(db)[f"{SLUG}-branch-main"] == ("P2", None)
    assert routers(tmp_path)["routers"]["router-domain-1"]["service"] == (
        "deployment-N@docker"
    )
    db.succeeded.add("N")
    rollback(db, tmp_path, prod=PROD)
    assert holders(db)[SLUG] == ("P2", "N")
    assert holders(db)[f"{SLUG}-env-id-prod"] == ("P2", "N")
    assert routers(tmp_path)["routers"]["router-domain-1"]["service"] == (
        "deployment-P2@docker"
    )
