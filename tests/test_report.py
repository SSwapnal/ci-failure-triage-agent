import pytest

from ci_triage.llm import MockClassifier
from ci_triage.models import TriageItem
from ci_triage.report import bug_drafts, render_report, repro_command


@pytest.fixture(scope="module")
def items(clusters):
    clf = MockClassifier()
    return [
        TriageItem(evidence=c, classification=(k := clf.classify(c)), needs_review=k.confidence < 0.7)
        for c in clusters
    ]


def test_report_has_all_sections(runs, histories, items):
    md = render_report(runs, items, histories, "mock", 0.7)
    for heading in (
        "## Summary",
        "## Product bugs",
        "## Test-code bugs",
        "## Flaky tests",
        "## Environment / infrastructure",
        "## Needs human review",
        "## Test history",
        "## Bug report drafts",
    ):
        assert heading in md
    assert "9 on `main`" in md
    assert "21 test failures grouped into 6 signatures" in md
    assert "\n\n\n" not in md


def test_review_items_are_not_drafted(items):
    drafts = bug_drafts(items)
    assert {d.labels[1] for d in drafts} == {"product-bug", "test-code-bug"}
    assert all("test_export_csv_header_order" not in d.body for d in drafts)


def test_bug_draft_contents(items):
    draft = next(d for d in bug_drafts(items) if "OrderPricingTest" in d.title)
    assert draft.title.startswith("OrderPricingTest.appliesBulkDiscountAboveThreshold: AssertionFailedError")
    assert "`9c41e7a` pricing: move bulk discount thresholds to config" in draft.body
    assert "mvn -Dtest=OrderPricingTest#appliesBulkDiscountAboveThreshold test" in draft.body
    assert f"<!-- triage-signature: {draft.signature_id} -->" in draft.body
    assert len(draft.title) <= 120


def test_repro_commands():
    assert repro_command("tests.api.test_a::test_b", "python") == 'pytest "tests/api/test_a.py::test_b"'
    assert repro_command("com.acme.FooTest::bar", "java") == "mvn -Dtest=FooTest#bar test"
