# A runner container's filesystem survives restarts. This file records that setup
# (clone, install, build, pre-deploy) already finished, so a restart only starts the app.
# It lives in /tmp, outside the user's app directory.
READY_MARKER = "/tmp/.devpush-ready"


def runner_command(
    setup: list[str],
    resume: list[str],
    start: list[str],
    marker: str = READY_MARKER,
) -> str:
    """Build the shell script a runner container executes.

    First start: run `setup`, mark the container ready, then `start`.
    Any later start (a restart after a reboot, a Docker restart or a crash): the
    marker exists, so run only `resume` (for example the `cd` into the root
    directory) and `start`. The clone needs a GitHub token that expires after about
    an hour, so repeating it on a restart would fail.

    A setup that fails never writes the marker, so the next start runs it again.
    """
    first_start = " && ".join([*setup, f"touch {marker}", *start])
    restart = " && ".join([*resume, *start])

    return f"if [ -f {marker} ]; then {restart}; else {first_start}; fi"
