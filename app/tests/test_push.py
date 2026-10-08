import pytest

from utils.push import ZERO_SHA, get_push_commit, is_release_tag, parse_ref

SHA = "a" * 40
TAG_OBJECT_SHA = "b" * 40


def payload(**overrides):
    data = {
        "ref": "refs/heads/main",
        "after": SHA,
        "deleted": False,
        "pusher": {"name": "bryanveloso"},
        "head_commit": {
            "id": SHA,
            "message": "Fix the footer.",
            "timestamp": "2026-10-08T12:00:00-07:00",
        },
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("refs/heads/main", ("branch", "main")),
        ("refs/heads/feature/a/b", ("branch", "feature/a/b")),
        ("refs/tags/v1.2.0", ("tag", "v1.2.0")),
        ("refs/tags/release-1", ("tag", "release-1")),
    ],
)
def test_parse_ref(ref, expected):
    assert parse_ref(ref) == expected


@pytest.mark.parametrize(
    "ref", ["refs/pull/1/head", "refs/heads/", "refs/tags/", "main", "", None]
)
def test_unsupported_refs(ref):
    assert parse_ref(ref) is None


@pytest.mark.parametrize(
    "name,expected",
    [
        ("v1.2.0", True),
        ("v2", True),
        ("V1.0", False),
        ("release-v1", False),
        ("1.0.0", False),
        ("", False),
    ],
)
def test_release_tags(name, expected):
    assert is_release_tag(name) is expected


def test_branch_push_commit():
    assert get_push_commit(payload()) == {
        "sha": SHA,
        "author": {"login": "bryanveloso"},
        "commit": {
            "message": "Fix the footer.",
            "author": {"date": "2026-10-08T12:00:00-07:00"},
        },
    }


def test_deleted_ref_is_ignored():
    data = payload(
        ref="refs/tags/v1.2.0", deleted=True, after=ZERO_SHA, head_commit=None
    )
    assert get_push_commit(data) is None


def test_zero_sha_is_ignored():
    assert get_push_commit(payload(after=ZERO_SHA, head_commit=None)) is None


def test_annotated_tag_uses_head_commit_id():
    data = payload(ref="refs/tags/v1.2.0", after=TAG_OBJECT_SHA)
    assert get_push_commit(data)["sha"] == SHA


def test_lightweight_tag_falls_back_to_after():
    data = payload(ref="refs/tags/v1.2.0", head_commit=None)
    commit = get_push_commit(data)
    assert commit["sha"] == SHA
    assert commit["commit"]["message"] == ""
    assert commit["commit"]["author"]["date"] is None


def test_branch_push_sha_is_after_even_if_head_differs():
    data = payload(after=SHA, head_commit={"id": TAG_OBJECT_SHA, "message": "x"})
    assert get_push_commit(data)["sha"] == SHA

