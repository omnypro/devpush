import logging

logger = logging.getLogger(__name__)

# Restarts after a host reboot or a Docker restart, but not after a deliberate stop,
# so containers devpush stops on purpose stay stopped.
RESTART_POLICY = {"Name": "unless-stopped"}


async def keep_running_after_reboot(docker_client, container_id: str | None) -> bool:
    """Give a runner container a restart policy once its deployment has succeeded.

    The policy is not set when the container is created: a runner executes the
    whole clone, install, build and start pipeline in one command, so a failed
    build would be restarted over and over until the failure handler removed it.
    Best effort: a failure here is logged and reported, never raised.
    """
    if not container_id:
        return False

    try:
        await docker_client._query_json(
            f"containers/{container_id}/update",
            method="POST",
            data={"RestartPolicy": RESTART_POLICY},
        )
    except Exception as error:
        logger.warning(
            "Could not set the restart policy on container %s: %s", container_id, error
        )
        return False

    return True
