import hashlib
import re

from utils.environment import is_promote_only

MAX_LABEL_LENGTH = 63
FINALIZE_ERROR = (
    "Failed to finalize deployment (aliases/routing). The app may still be running."
)


class AliasError(ValueError):
    pass


def fit_label(label: str, seed: str | None = None) -> str:
    """Return the label unchanged if it fits, else truncate it and add a hash suffix."""
    if len(label) <= MAX_LABEL_LENGTH:
        return label
    digest = hashlib.sha256((seed or label).encode()).hexdigest()[:8]
    head = label[: MAX_LABEL_LENGTH - len(digest) - 1].rstrip("-")
    return f"{head}-{digest}"


def branch_subdomain(project_slug: str, branch: str) -> str | None:
    sanitized = re.sub(r"[^a-zA-Z0-9-]", "-", branch).lower()
    if not sanitized:
        return None
    return fit_label(
        f"{project_slug}-branch-{sanitized}", f"{project_slug}:branch:{branch}"
    )


def environment_subdomain(project_slug: str, environment: dict) -> str:
    if environment.get("id") == "prod":
        return project_slug
    slug = environment.get("slug")
    return fit_label(f"{project_slug}-env-{slug}", f"{project_slug}:env:{slug}")


def environment_id_subdomain(project_slug: str, environment_id: str) -> str:
    return fit_label(f"{project_slug}-env-id-{environment_id}")


def alias_subdomains(
    project_slug: str,
    environment_id: str,
    environment: dict | None,
    branch: str | None,
) -> dict[str, str]:
    """Subdomains a deployment should hold, keyed by alias type."""
    values: dict[str, str] = {}

    if branch and not (environment and is_promote_only(environment)):
        subdomain = branch_subdomain(project_slug, branch)
        if subdomain:
            values["branch"] = subdomain

    if environment_id == "prod":
        values["environment"] = project_slug
    elif environment:
        values["environment"] = environment_subdomain(project_slug, environment)

    values["environment_id"] = environment_id_subdomain(project_slug, environment_id)
    return values


def check_label(label: str) -> str:
    if not label:
        raise AliasError("Alias subdomain is empty.")
    if len(label) > MAX_LABEL_LENGTH:
        raise AliasError(
            f'Alias "{label}" is {len(label)} characters; subdomains are limited '
            f"to {MAX_LABEL_LENGTH}. Shorten the project or branch name."
        )
    return label


def finalize_error_message(exc: Exception) -> str:
    if isinstance(exc, AliasError):
        return str(exc)
    if "value too long" in str(exc):
        return (
            f"An alias for this deployment is longer than {MAX_LABEL_LENGTH} "
            "characters. Shorten the project or branch name."
        )
    return FINALIZE_ERROR
