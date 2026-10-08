import pytest

from utils.environment import (
    get_environment_for_branch,
    get_production_environment,
    group_branches_by_environment,
    is_promote_only,
)


def envs(prod_branch="main"):
    prod = {"id": "prod", "slug": "production", "status": "active"}
    if prod_branch is not ...:
        prod["branch"] = prod_branch
    return [
        prod,
        {"id": "a1b2c3d4", "slug": "staging", "branch": "main", "status": "active"},
        {"id": "e5f6a7b8", "slug": "preview", "branch": "*", "status": "active"},
    ]


def test_legacy_prod_branch_still_matches():
    legacy = [envs()[0], envs()[2]]
    assert get_environment_for_branch("main", legacy)["id"] == "prod"
    assert get_environment_for_branch("feature/x", legacy)["slug"] == "preview"


@pytest.mark.parametrize("branch", ["", None, "   ", ...])
def test_promote_only_prod_shapes(branch):
    environments = envs(branch)
    assert is_promote_only(environments[0])
    assert get_environment_for_branch("main", environments)["slug"] == "staging"
    assert get_environment_for_branch("feature/x", environments)["slug"] == "preview"


def test_prod_with_branch_is_not_promote_only():
    assert not is_promote_only({"id": "prod", "branch": "main"})


def test_empty_branch_never_matches():
    environments = envs("")
    assert get_environment_for_branch("", environments) is None
    assert get_environment_for_branch(None, environments) is None


def test_non_prod_empty_pattern_never_matches():
    environments = [
        {"id": "prod", "slug": "production", "branch": "", "status": "active"},
        {"id": "a1b2c3d4", "slug": "staging", "branch": "", "status": "active"},
    ]
    assert get_environment_for_branch("main", environments) is None


def test_prod_found_by_id_not_position():
    prod, staging, preview = envs("")
    environments = [staging, preview, prod]
    assert get_production_environment(environments)["id"] == "prod"
    assert get_environment_for_branch("main", environments)["slug"] == "staging"


def test_list_order_is_priority():
    prod, staging, preview = envs("")
    assert get_environment_for_branch("main", [prod, preview, staging])["slug"] == "preview"


def test_production_environment_missing():
    assert get_production_environment([]) is None
    assert get_environment_for_branch("main", []) is None


def test_wildcard_patterns():
    environments = [
        {"id": "prod", "slug": "production", "branch": "", "status": "active"},
        {"id": "1", "slug": "suffix", "branch": "*-hotfix", "status": "active"},
        {"id": "2", "slug": "prefix", "branch": "release/*", "status": "active"},
        {"id": "3", "slug": "middle", "branch": "feat/*/wip", "status": "active"},
    ]
    assert get_environment_for_branch("a-hotfix", environments)["slug"] == "suffix"
    assert get_environment_for_branch("release/1", environments)["slug"] == "prefix"
    assert get_environment_for_branch("feat/x/wip", environments)["slug"] == "middle"
    assert get_environment_for_branch("other", environments) is None


def test_group_branches_leaves_promote_only_prod_empty():
    result = group_branches_by_environment(envs(""), ["main", "feature/x"])
    assert result["production"] == []
    assert result["staging"] == ["main"]
    assert result["preview"] == ["feature/x"]
