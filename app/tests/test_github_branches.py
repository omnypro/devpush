import asyncio

import httpx
import pytest

from services.github import GitHubService

REPO_ID = 1234


class Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def service():
    return GitHubService("client", "secret", "1", "key")


def fake_github(monkeypatch, names):
    """Serve `names` the way GitHub's branches endpoint does: pages of up to per_page (default 30)."""
    calls = []

    def get(url, headers=None, params=None):
        params = params or {}
        per_page = int(params.get("per_page", 30))
        page = int(params.get("page", 1))
        calls.append({"url": url, "per_page": per_page, "page": page})
        start = (page - 1) * per_page
        return Response([{"name": name} for name in names[start : start + per_page]])

    monkeypatch.setattr(httpx, "get", get)
    return calls


def branches(monkeypatch, names):
    calls = fake_github(monkeypatch, names)
    result = asyncio.run(service().get_repository_branches("token", REPO_ID))
    return [branch["name"] for branch in result], calls


def test_branches_past_the_first_default_page_are_returned(monkeypatch):
    names = [f"docs/{i:02d}" for i in range(37)] + ["main", "staging"]

    result, _ = branches(monkeypatch, names)

    assert "main" in result
    assert result == names


def test_branches_span_several_full_pages(monkeypatch):
    names = [f"feat/{i:03d}" for i in range(250)]

    result, calls = branches(monkeypatch, names)

    assert result == names
    assert [call["page"] for call in calls] == [1, 2, 3]
    assert {call["per_page"] for call in calls} == {100}


def test_branches_stop_after_a_short_page(monkeypatch):
    result, calls = branches(monkeypatch, ["main"])

    assert result == ["main"]
    assert len(calls) == 1


def test_branches_on_an_exact_page_boundary_stop_on_the_empty_page(monkeypatch):
    names = [f"feat/{i:03d}" for i in range(100)]

    result, calls = branches(monkeypatch, names)

    assert result == names
    assert [call["page"] for call in calls] == [1, 2]


def test_branches_of_an_empty_repository(monkeypatch):
    result, calls = branches(monkeypatch, [])

    assert result == []
    assert len(calls) == 1


def test_branches_request_targets_the_repository_by_id(monkeypatch):
    _, calls = branches(monkeypatch, ["main"])

    assert calls[0]["url"] == f"https://api.github.com/repositories/{REPO_ID}/branches"


def test_a_failed_request_raises(monkeypatch):
    class Failing(Response):
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "forbidden", request=httpx.Request("GET", "http://x"), response=None
            )

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Failing([]))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(service().get_repository_branches("token", REPO_ID))
