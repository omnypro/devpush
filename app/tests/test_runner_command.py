import subprocess

import pytest

from services.runner_command import READY_MARKER, runner_command


def run(script, cwd):
    return subprocess.run(
        ["/bin/sh", "-c", script], cwd=cwd, capture_output=True, text=True, timeout=20
    )


@pytest.fixture
def work(tmp_path):
    (tmp_path / "web").mkdir()
    return tmp_path


def command(work, setup=None, resume=None, start=None):
    marker = work / "ready"
    log = work / "log"
    return (
        runner_command(
            setup=setup if setup is not None else [f"echo setup >> {log}"],
            resume=resume if resume is not None else [],
            start=start if start is not None else [f"echo start >> {log}"],
            marker=str(marker),
        ),
        marker,
        log,
    )


def lines(path):
    return path.read_text().split() if path.exists() else []


def test_the_first_start_sets_up_then_starts(work):
    script, marker, log = command(work)

    result = run(script, work)

    assert result.returncode == 0
    assert lines(log) == ["setup", "start"]
    assert marker.exists()


def test_a_restart_skips_setup_and_only_starts(work):
    script, marker, log = command(work)
    run(script, work)

    result = run(script, work)

    assert result.returncode == 0
    assert lines(log) == ["setup", "start", "start"]


def test_a_failed_setup_leaves_no_marker_and_does_not_start(work):
    script, marker, log = command(work, setup=["false", "echo never"])

    result = run(script, work)

    assert result.returncode != 0
    assert not marker.exists()
    assert lines(log) == []


def test_after_a_failed_setup_the_next_start_sets_up_again(work):
    log = work / "log"
    failing, marker, _ = command(work, setup=[f"echo try >> {log}", "false"])
    run(failing, work)

    run(failing, work)

    assert lines(log) == ["try", "try"]
    assert not marker.exists()


def test_the_marker_is_written_only_after_setup_and_before_the_app_runs(work):
    marker = work / "ready"
    log = work / "log"
    script = runner_command(
        setup=[f"test ! -e {marker} && echo no-marker-during-setup >> {log}"],
        resume=[],
        start=[f"test -e {marker} && echo marker-present-at-start >> {log}"],
        marker=str(marker),
    )

    run(script, work)

    assert lines(log) == ["no-marker-during-setup", "marker-present-at-start"]


def test_a_restart_goes_back_to_the_root_directory_before_starting(work):
    log = work / "log"
    script = runner_command(
        setup=["cd web", "echo built"],
        resume=["cd web"],
        start=[f"basename $(pwd) >> {log}"],
        marker=str(work / "ready"),
    )
    run(script, work)

    run(script, work)

    assert lines(log) == ["web", "web"]


def test_a_missing_root_directory_still_fails_the_first_start(work):
    script, marker, log = command(
        work,
        setup=["test -d nope || { echo missing >&2; exit 1; }"],
        resume=["cd nope"],
    )

    result = run(script, work)

    assert result.returncode == 1
    assert not marker.exists()
    assert lines(log) == []


def test_the_exit_code_of_a_crashing_app_is_passed_on(work):
    script, marker, log = command(work, start=["exit 7"])

    first = run(script, work)
    second = run(script, work)

    assert first.returncode == 7
    assert second.returncode == 7


def test_the_default_marker_lives_in_tmp_not_in_the_users_app_directory():
    assert READY_MARKER.startswith("/tmp/")


def test_the_script_never_clones_on_the_restart_path():
    script = runner_command(
        setup=["git init -q", "git fetch https://example.invalid/x.git abc"],
        resume=[],
        start=["echo start"],
    )

    restart_branch = script.split("else", 1)[0]

    assert "git " not in restart_branch
