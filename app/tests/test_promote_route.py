import asyncio
from pathlib import Path
from types import SimpleNamespace

import jinja2
import pytest
from fastapi import HTTPException

from routers.project import project_promote

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def test_promote_rejects_deployment_from_another_project():
    project = SimpleNamespace(id="p1")
    deployment = SimpleNamespace(id="d1", project_id="p2")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            project_promote(
                request=None,
                project=project,
                current_user=None,
                team_and_membership=(None, None),
                deployment=deployment,
                db=None,
                redis_client=None,
                queue=None,
            )
        )
    assert exc.value.status_code == 404


def render_options(**overrides):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        extensions=["jinja2.ext.i18n"],
        autoescape=True,
    )
    env.install_null_translations()
    env.globals["_"] = lambda s, **kw: s % kw if kw else s
    env.globals["url_for"] = lambda name, **kw: f"/{name}/{kw.get('deployment_id')}"
    deployment = SimpleNamespace(
        id="dep1",
        commit_sha="abcdef1234",
        conclusion="succeeded",
        environment_id="a1b2c3d4",
        environment=SimpleNamespace(id="a1b2c3d4"),
    )
    for key, value in overrides.items():
        setattr(deployment, key, value)
    return env.get_template("deployment/partials/_options.html").render(
        deployment=deployment,
        team=SimpleNamespace(slug="t"),
        project=SimpleNamespace(name="p"),
        env_aliases={},
    )


def test_options_promote_dialog_has_unique_id_and_enabled_button():
    html = render_options()
    assert 'id="dialog-promote-dep1"' in html
    button = html.split("getElementById('dialog-promote-dep1')")[1].split("</button>")[0]
    assert "disabled" not in button


def test_options_promote_disabled_for_prod_deployment():
    html = render_options(environment_id="prod")
    assert 'id="dialog-promote-dep1"' not in html
    button = html.split("getElementById('dialog-promote-dep1')")[1].split("</button>")[0]
    assert "disabled" in button
