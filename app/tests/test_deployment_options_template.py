import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def translate(message, **values):
    return message % values if values else message


def url_for(name, **values):
    return f"/{name}/{values.get('deployment_id', '')}"


@pytest.fixture(scope="module")
def render():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)
    env.globals["_"] = translate
    env.globals["url_for"] = url_for
    template = env.get_template("deployment/partials/_options.html")

    def render_row(deployment, env_aliases):
        return template.render(
            deployment=deployment,
            env_aliases=env_aliases,
            team=SimpleNamespace(slug="marketing"),
            project=SimpleNamespace(name="example.com"),
        )

    return render_row


def deployment(identifier, environment_id="staging", conclusion="succeeded"):
    return SimpleNamespace(
        id=identifier,
        commit_sha=identifier[:1] * 40,
        conclusion=conclusion,
        environment_id=environment_id,
        environment=SimpleNamespace(id=environment_id, name=environment_id.title()),
    )


def rollback_target(deployment_id):
    return SimpleNamespace(previous_deployment_id=deployment_id)


def page(render):
    """The rows of one list page: a prod deployment and two staging ones, both
    environments having a previous deployment that can be rolled back to."""
    rows = [
        ("aaaa1111", deployment("aaaa1111", "prod"), {"prod": rollback_target("zzzz")}),
        ("bbbb2222", deployment("bbbb2222", "staging"), {"staging": rollback_target("bbbb2222")}),
        ("cccc3333", deployment("cccc3333", "prod"), {"prod": rollback_target("cccc3333")}),
        ("dddd4444", deployment("dddd4444", "staging"), {"staging": rollback_target("zzzz")}),
    ]
    return [(identifier, render(row, aliases)) for identifier, row, aliases in rows]


def dialog_ids(html):
    return re.findall(r'<dialog[^>]*\sid="([^"]+)"', html)


def opened_ids(html):
    """Dialog ids opened by the enabled menu items; a disabled item cannot be clicked."""
    opened = []
    for button in re.findall(r'<button\s[^>]*role="menuitem"[^>]*>', html):
        if re.search(r"\sdisabled(\s|>)", button):
            continue
        opened += re.findall(r"getElementById\('([^']+)'\)", button)
    return opened


def test_every_dialog_on_a_list_page_has_a_unique_id(render):
    combined = "".join(html for _, html in page(render))

    duplicates = [name for name, count in Counter(dialog_ids(combined)).items() if count > 1]

    assert duplicates == []


def test_each_row_only_opens_its_own_dialogs(render):
    for identifier, html in page(render):
        own = set(dialog_ids(html))
        for opened in opened_ids(html):
            assert opened in own, f"{identifier} opens {opened}, which is not its own dialog"


@pytest.mark.parametrize("kind", ["redeploy", "rollback", "promote"])
def test_dialog_ids_name_the_deployment_they_belong_to(render, kind):
    for identifier, html in page(render):
        ids = [name for name in dialog_ids(html) if name.startswith(f"dialog-{kind}")]
        assert all(identifier in name for name in ids)


def test_a_row_that_cannot_roll_back_renders_no_rollback_dialog(render):
    html = render(deployment("aaaa1111", "prod"), {"prod": rollback_target("zzzz")})

    assert not any(name.startswith("dialog-rollback") for name in dialog_ids(html))


def test_every_row_has_a_redeploy_dialog_for_its_own_deployment(render):
    for identifier, html in page(render):
        assert f"dialog-redeploy-{identifier}" in dialog_ids(html)
