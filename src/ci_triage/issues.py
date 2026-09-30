"""GitHub issue filing via the REST API. Dry-run unless explicitly disabled."""

from __future__ import annotations

import httpx

from ci_triage.models import BugDraft, IssueResult

API = "https://api.github.com"


def file_issues(
    drafts: list[BugDraft],
    repo: str | None,
    token: str | None,
    dry_run: bool = True,
    client: httpx.Client | None = None,
) -> list[IssueResult]:
    """Create one issue per draft, skipping drafts whose signature is already filed.

    With ``dry_run=True`` nothing leaves the machine; the caller writes the
    payloads to disk for review.
    """
    if dry_run:
        return [IssueResult(signature_id=d.signature_id, status="dry-run") for d in drafts]
    if not repo or not token:
        raise ValueError("filing issues requires --repo owner/name and GITHUB_TOKEN")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    own_client = client is None
    client = client or httpx.Client(base_url=API, headers=headers, timeout=30)
    try:
        return [_file_one(client, repo, d) for d in drafts]
    finally:
        if own_client:
            client.close()


def _file_one(client: httpx.Client, repo: str, draft: BugDraft) -> IssueResult:
    try:
        # The signature marker in the body makes re-runs idempotent.
        q = f'repo:{repo} is:issue is:open in:body "triage-signature: {draft.signature_id}"'
        found = client.get("/search/issues", params={"q": q})
        found.raise_for_status()
        existing = found.json().get("items", [])
        if existing:
            return IssueResult(signature_id=draft.signature_id, status="exists", url=existing[0]["html_url"])

        resp = client.post(
            f"/repos/{repo}/issues",
            json={"title": draft.title, "body": draft.body, "labels": draft.labels},
        )
        resp.raise_for_status()
        return IssueResult(signature_id=draft.signature_id, status="created", url=resp.json()["html_url"])
    except httpx.HTTPError as exc:
        return IssueResult(signature_id=draft.signature_id, status="error", detail=str(exc))
