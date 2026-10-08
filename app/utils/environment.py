def is_promote_only(environment: dict) -> bool:
    """Whether an environment has no branch pattern and only changes by promotion."""
    return not (environment.get("branch") or "").strip()


def get_production_environment(environments) -> dict | None:
    """Find the production environment by its fixed ID."""
    return next((env for env in environments if env.get("id") == "prod"), None)


def get_environment_for_branch(branch, environments) -> dict | None:
    """
    Find the highest priority environment that matches a branch.

    Args:
        branch: The branch name
        environments: List of environments in priority order (highest first)

    Returns:
        The matching environment or None if no match is found
    """
    if not branch:
        return None

    production_env = get_production_environment(environments)
    if (
        production_env
        and not is_promote_only(production_env)
        and production_env["branch"] == branch
    ):
        return production_env

    for environment in environments:
        if environment.get("id") == "prod":
            continue

        pattern = environment.get("branch") or ""
        if not pattern:
            continue

        if pattern == branch:
            return environment

        if '*' in pattern:
            if pattern.startswith('*'):
                if branch.endswith(pattern[1:]):
                    return environment
            elif pattern.endswith('*'):
                if branch.startswith(pattern[:-1]):
                    return environment
            else:
                prefix, suffix = pattern.split('*', 1)
                if branch.startswith(prefix) and branch.endswith(suffix):
                    return environment

    return None


def group_branches_by_environment(environments, branches) -> dict[str, list[str]]:
    """
    Group branches by their matching environments based on priority.
    
    Args:
        environments: List of environments in priority order (highest first)
        branches: List of all branch names
    
    Returns:
        Dictionary mapping environment slugs to lists of matching branch names
    """
    # Initialize the result dictionary with empty lists for each environment
    result = {environment['slug']: [] for environment in environments}
    
    # Add an 'unmatched' category for branches that don't match any environment
    result['unmatched'] = []
    
    for branch in branches:
        # Find the highest priority environment that matches this branch
        matching_env = get_environment_for_branch(branch, environments)
        
        if matching_env:
            # Add this branch to its matching environment
            result[matching_env['slug']].append(branch)
        else:
            # If no environment matches, add to unmatched
            result['unmatched'].append(branch)
    
    return result