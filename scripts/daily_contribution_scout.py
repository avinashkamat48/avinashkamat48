"""Create or refresh a daily GitHub contribution candidate queue.

This intentionally does not post reviews, issues, or pull requests to other
projects. It finds realistic opportunities and records them in this repo so a
human can choose what is worth doing.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
import urllib.parse
import urllib.request


API_ROOT = "https://api.github.com"
QUEUE_TITLE = "Daily contribution queue"

SEARCHES = [
    {
        "heading": "Review candidates",
        "query": "is:pr is:open review:none archived:false",
        "sort": "updated",
        "order": "desc",
    },
    {
        "heading": "Good first issues",
        "query": 'is:issue is:open label:"good first issue" archived:false',
        "sort": "updated",
        "order": "desc",
    },
    {
        "heading": "Documentation gaps",
        "query": 'is:issue is:open label:documentation archived:false',
        "sort": "updated",
        "order": "desc",
    },
    {
        "heading": "Bug triage",
        "query": "is:issue is:open label:bug archived:false comments:<4",
        "sort": "updated",
        "order": "desc",
    },
]


def request_json(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        method=method,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "daily-contribution-scout",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def search_issues(token: str, query: str, sort: str, order: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": 8,
        }
    )
    return request_json("GET", f"/search/issues?{params}", token).get("items", [])


def compact_item(item: dict) -> str:
    labels = ", ".join(label["name"] for label in item.get("labels", [])[:3])
    comments = item.get("comments", 0)
    suffix = f" | labels: {labels}" if labels else ""
    return f"- [{item['title']}]({item['html_url']}) | comments: {comments}{suffix}"


def find_queue_issue(token: str, repository: str) -> int | None:
    owner, repo = repository.split("/", 1)
    params = urllib.parse.urlencode({"state": "open", "per_page": 30})
    issues = request_json("GET", f"/repos/{owner}/{repo}/issues?{params}", token)
    for issue in issues:
        if issue.get("title") == QUEUE_TITLE and "pull_request" not in issue:
            return int(issue["number"])
    return None


def upsert_queue_issue(token: str, repository: str, body: str) -> None:
    owner, repo = repository.split("/", 1)
    issue_number = find_queue_issue(token, repository)
    payload = {"title": QUEUE_TITLE, "body": body}
    if issue_number is None:
        request_json("POST", f"/repos/{owner}/{repo}/issues", token, payload)
    else:
        request_json("PATCH", f"/repos/{owner}/{repo}/issues/{issue_number}", token, payload)


def build_body(token: str) -> str:
    today = dt.datetime.now(dt.UTC).date().isoformat()
    sections = [
        f"# Daily contribution queue - {today}",
        "",
        "This queue is generated in the cloud. Pick only items where you can leave a concrete fix, test, reproduction, or review finding.",
        "",
        "Quality rules:",
        "- Do not post generic review comments.",
        "- Do not open duplicate issues.",
        "- Do not split tiny edits into artificial commits.",
        "- Prefer fewer useful contributions over noisy volume.",
    ]

    for search in SEARCHES:
        sections.extend(["", f"## {search['heading']}", ""])
        try:
            items = search_issues(token, search["query"], search["sort"], search["order"])
        except Exception as exc:  # noqa: BLE001 - surfaced in the generated queue body.
            sections.append(f"- Search failed: `{type(exc).__name__}`")
            continue
        if not items:
            sections.append("- No candidates found.")
            continue
        sections.extend(compact_item(item) for item in items)

    sections.extend(
        [
            "",
            "## Suggested daily flow",
            "",
            "1. Choose a small number of candidates from this issue.",
            "2. Inspect the actual diff or reproduction before commenting.",
            "3. Make the contribution manually or with Codex assistance.",
            "4. Close stale candidates by editing this queue, not by posting noise upstream.",
        ]
    )
    return "\n".join(sections)


def main() -> None:
    token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    body = build_body(token)
    upsert_queue_issue(token, repository, textwrap.dedent(body).strip() + "\n")


if __name__ == "__main__":
    main()
