import httpx
import pytest

from ci_triage.issues import API, file_issues
from ci_triage.models import BugDraft

DRAFT = BugDraft(
    signature_id="abc123", title="t", body="b <!-- triage-signature: abc123 -->", labels=["ci-triage"]
)


def _client(handler):
    return httpx.Client(base_url=API, transport=httpx.MockTransport(handler))


def test_dry_run_makes_no_requests():
    def handler(request):
        raise AssertionError("no HTTP in dry-run")

    [r] = file_issues([DRAFT], repo=None, token=None, dry_run=True, client=_client(handler))
    assert r.status == "dry-run"


def test_requires_repo_and_token():
    with pytest.raises(ValueError):
        file_issues([DRAFT], repo="o/r", token=None, dry_run=False)


def test_creates_issue_when_not_already_filed():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            assert "triage-signature: abc123" in request.url.params["q"]
            return httpx.Response(200, json={"items": []})
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/issues/7"})

    [r] = file_issues([DRAFT], repo="o/r", token="t", dry_run=False, client=_client(handler))
    assert r.status == "created" and r.url.endswith("/7")
    assert seen == [("GET", "/search/issues"), ("POST", "/repos/o/r/issues")]


def test_skips_existing_issue():
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"items": [{"html_url": "https://github.com/o/r/issues/3"}]})

    [r] = file_issues([DRAFT], repo="o/r", token="t", dry_run=False, client=_client(handler))
    assert r.status == "exists"


def test_http_errors_are_reported_not_raised():
    def handler(request):
        return httpx.Response(403, json={"message": "forbidden"})

    [r] = file_issues([DRAFT], repo="o/r", token="t", dry_run=False, client=_client(handler))
    assert r.status == "error" and "403" in r.detail
