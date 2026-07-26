from __future__ import annotations

import json
from pathlib import Path

import requests

LINEAR_API_URL = "https://api.linear.app/graphql"
DEFAULT_CACHE_PATH = Path(".cache/linear_cache.json")

QUERY = """
query($after: String) {
  issues(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      identifier title estimate
      state { name type }
      assignee { name }
      project { id name }
      completedAt createdAt startedAt
    }
  }
}
"""


class LinearError(RuntimeError):
    pass


def fetch_issues(api_key: str) -> list[dict]:
    issues: list[dict] = []
    after = None
    while True:
        response = requests.post(
            LINEAR_API_URL,
            json={"query": QUERY, "variables": {"after": after}},
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if "errors" in payload:
            raise LinearError(str(payload["errors"]))

        data = payload["data"]["issues"]
        issues.extend(data["nodes"])
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]

    return issues


def get_issues(
    api_key: str,
    cache_path: Path = DEFAULT_CACHE_PATH,
    use_cache: bool = True,
) -> list[dict]:
    if use_cache and cache_path.exists():
        with cache_path.open() as f:
            return json.load(f)

    issues = fetch_issues(api_key)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w") as f:
        json.dump(issues, f, indent=2)
    return issues


def index_by_identifier(issues: list[dict]) -> dict[str, dict]:
    return {issue["identifier"]: issue for issue in issues}
