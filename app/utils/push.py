ZERO_SHA = "0" * 40


def parse_ref(ref: str | None) -> tuple[str, str] | None:
    """Split a pushed git ref into ("branch" | "tag", name)."""
    for prefix, kind in (("refs/heads/", "branch"), ("refs/tags/", "tag")):
        if ref and ref.startswith(prefix) and len(ref) > len(prefix):
            return kind, ref[len(prefix) :]
    return None


def is_release_tag(name: str) -> bool:
    return name.startswith("v")


def get_push_commit(data: dict) -> dict | None:
    """Commit payload for a push, or None when the push deleted the ref."""
    if data.get("deleted"):
        return None

    head = data.get("head_commit") or {}
    if (data.get("ref") or "").startswith("refs/tags/"):
        # An annotated tag's "after" is the tag object, not the commit.
        sha = head.get("id") or data.get("after")
    else:
        sha = data.get("after") or head.get("id")
    if not sha or sha == ZERO_SHA:
        return None

    return {
        "sha": sha,
        "author": {"login": (data.get("pusher") or {}).get("name")},
        "commit": {
            "message": head.get("message") or "",
            "author": {"date": head.get("timestamp")},
        },
    }
