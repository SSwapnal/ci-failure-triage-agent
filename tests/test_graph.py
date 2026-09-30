import shutil

from ci_triage.graph import build_graph
from ci_triage.llm import MockClassifier


def test_end_to_end_mock_run(sample_dir):
    state = build_graph(MockClassifier()).invoke({"input_dir": str(sample_dir)})

    categories = sorted(i.classification.category for i in state["items"])
    assert categories == [
        "environment",
        "environment",
        "flaky_test",
        "product_bug",
        "product_bug",
        "test_code_bug",
    ]
    review = [i for i in state["items"] if i.needs_review]
    assert [i.evidence.tests for i in review] == [["tests.api.test_reports::test_export_csv_header_order"]]
    assert len(state["bug_drafts"]) == 2
    assert [r.status for r in state["issue_results"]] == ["dry-run", "dry-run"]
    assert "## Needs human review" in state["report_markdown"]


def test_threshold_controls_review_routing(sample_dir):
    state = build_graph(MockClassifier()).invoke({"input_dir": str(sample_dir), "confidence_threshold": 0.95})
    assert all(i.needs_review for i in state["items"])
    assert state["bug_drafts"] == []
    assert "issue_results" not in state  # file_issues is skipped when there is nothing to file


def test_all_green_input_skips_classification(tmp_path, sample_dir):
    run_dir = tmp_path / "runs" / "r1001"
    shutil.copytree(sample_dir / "runs" / "r1001", run_dir)  # r1001 is all green

    class ExplodingClassifier(MockClassifier):
        def classify(self, evidence):
            raise AssertionError("classifier must not be called without failures")

    state = build_graph(ExplodingClassifier()).invoke({"input_dir": str(tmp_path)})
    assert state["clusters"] == []
    assert "0 test failures grouped into 0 signatures" in state["report_markdown"]
