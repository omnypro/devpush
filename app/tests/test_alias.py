import re

import pytest

from utils.alias import (
    FINALIZE_ERROR,
    MAX_LABEL_LENGTH,
    AliasError,
    alias_subdomains,
    branch_subdomain,
    check_label,
    environment_id_subdomain,
    environment_subdomain,
    finalize_error_message,
    fit_label,
)

PROD = {"id": "prod", "slug": "production", "branch": "", "status": "active"}
LEGACY_PROD = {"id": "prod", "slug": "production", "branch": "main", "status": "active"}
STAGING = {"id": "a1b2c3d4", "slug": "staging", "branch": "main", "status": "active"}


def legacy_branch(slug, branch):
    return f"{slug}-branch-{re.sub(r'[^a-zA-Z0-9-]', '-', branch).lower()}"


def legacy_env(slug, environment):
    if environment["id"] == "prod":
        return slug
    return f"{slug}-env-{environment.get('slug')}"


def legacy_env_id(slug, environment_id):
    return f"{slug}-env-id-{environment_id}"


@pytest.mark.parametrize(
    "slug,branch,environment",
    [
        ("cenitlaw-respro", "main", STAGING),
        ("certezzadata-respro", "feature/Login_Page", STAGING),
        ("resolutionprocessing-respro", "feature/advocacy", STAGING),
        ("a" * 40, "x" * 15, STAGING),
        ("site-respro", "main", {"id": "x1", "slug": "my.env_2", "branch": "*"}),
        ("site-respro", "main", PROD),
    ],
)
def test_short_names_are_byte_identical_to_legacy_formulas(slug, branch, environment):
    assert len(legacy_branch(slug, branch)) <= MAX_LABEL_LENGTH
    assert branch_subdomain(slug, branch) == legacy_branch(slug, branch)
    assert environment_subdomain(slug, environment) == legacy_env(slug, environment)
    assert environment_id_subdomain(slug, environment["id"]) == legacy_env_id(
        slug, environment["id"]
    )


def test_pinned_live_hostnames():
    assert environment_subdomain("cenitlaw-respro", PROD) == "cenitlaw-respro"
    assert (
        environment_subdomain("cenitlaw-respro", STAGING)
        == "cenitlaw-respro-env-staging"
    )
    assert (
        environment_id_subdomain("cenitlaw-respro", "prod")
        == "cenitlaw-respro-env-id-prod"
    )
    assert (
        branch_subdomain("cenitlaw-respro", "feature/Login_Page")
        == "cenitlaw-respro-branch-feature-login-page"
    )


def test_exactly_63_is_unchanged_and_64_is_hashed():
    assert fit_label("a" * 63) == "a" * 63
    hashed = fit_label("a" * 64)
    assert len(hashed) <= MAX_LABEL_LENGTH
    assert re.fullmatch(r"a+-[0-9a-f]{8}", hashed)


def test_long_label_is_deterministic_and_fits():
    branch = "feature/advocacy-landing-page-redesign-2026-q4-final"
    first = branch_subdomain("resolutionprocessing-respro", branch)
    assert first == branch_subdomain("resolutionprocessing-respro", branch)
    assert len(first) <= MAX_LABEL_LENGTH
    assert first.startswith("resolutionprocessing-respro-branch-feature-")
    assert not first[: -9].endswith("-")


def test_long_branches_with_shared_prefix_stay_distinct():
    base = "feature/" + "x" * 60
    assert branch_subdomain("site-respro", base + "-a") != branch_subdomain(
        "site-respro", base + "-b"
    )


def test_long_branches_that_sanitize_alike_stay_distinct():
    base = "feature/" + "x" * 60
    assert branch_subdomain("site-respro", base + "/a") != branch_subdomain(
        "site-respro", base + "-a"
    )


def test_long_environment_slug_fits():
    environment = {"id": "z9", "slug": "s" * 80, "branch": "*"}
    assert len(environment_subdomain("site-respro", environment)) <= MAX_LABEL_LENGTH


def test_promote_only_prod_gets_no_branch_alias():
    result = alias_subdomains("site-respro", "prod", PROD, "main")
    assert "branch" not in result
    assert result["environment"] == "site-respro"
    assert result["environment_id"] == "site-respro-env-id-prod"


def test_tag_promotion_gets_no_branch_alias():
    assert "branch" not in alias_subdomains("site-respro", "prod", PROD, "v1.2.0")


def test_legacy_prod_with_branch_keeps_branch_alias():
    result = alias_subdomains("site-respro", "prod", LEGACY_PROD, "main")
    assert result["branch"] == "site-respro-branch-main"


def test_staging_gets_all_three_aliases():
    assert alias_subdomains("site-respro", "a1b2c3d4", STAGING, "main") == {
        "branch": "site-respro-branch-main",
        "environment": "site-respro-env-staging",
        "environment_id": "site-respro-env-id-a1b2c3d4",
    }


def test_missing_environment_skips_environment_alias():
    result = alias_subdomains("site-respro", "gone1234", None, "main")
    assert "environment" not in result
    assert result["branch"] == "site-respro-branch-main"


def test_check_label():
    assert check_label("a" * 63) == "a" * 63
    with pytest.raises(AliasError, match="63"):
        check_label("a" * 64)
    with pytest.raises(AliasError):
        check_label("")


def test_finalize_error_message():
    assert finalize_error_message(AliasError("Alias too long.")) == "Alias too long."
    assert "63" in finalize_error_message(
        Exception("value too long for type character varying(63)")
    )
    assert finalize_error_message(RuntimeError("boom")) == FINALIZE_ERROR


def test_pinned_live_alias_sets():
    # Hand-derived from the pre-fork formulas in services/deployment.py.
    assert alias_subdomains("cenitlaw", "prod", LEGACY_PROD, "main") == {
        "branch": "cenitlaw-branch-main",
        "environment": "cenitlaw",
        "environment_id": "cenitlaw-env-id-prod",
    }
    assert alias_subdomains("certezzadata", "prod", LEGACY_PROD, "main") == {
        "branch": "certezzadata-branch-main",
        "environment": "certezzadata",
        "environment_id": "certezzadata-env-id-prod",
    }
    assert alias_subdomains("cenitlaw", STAGING["id"], STAGING, "main") == {
        "branch": "cenitlaw-branch-main",
        "environment": "cenitlaw-env-staging",
        "environment_id": "cenitlaw-env-id-a1b2c3d4",
    }
    assert alias_subdomains(
        "certezzadata", STAGING["id"], STAGING, "feature/Login_Page"
    ) == {
        "branch": "certezzadata-branch-feature-login-page",
        "environment": "certezzadata-env-staging",
        "environment_id": "certezzadata-env-id-a1b2c3d4",
    }
