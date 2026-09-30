import json

from typer.testing import CliRunner

from ci_triage.cli import app


def test_run_writes_report_and_drafts(tmp_path, sample_dir, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    result = CliRunner().invoke(app, ["run", "--input", str(sample_dir), "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "needs review: 1" in result.output
    assert (tmp_path / "triage-report.md").read_text().startswith("# CI Failure Triage Report")
    items = json.loads((tmp_path / "triage.json").read_text())
    assert len(items) == 6
    assert len(list((tmp_path / "bugs").glob("*.md"))) == 2
    payload = json.loads(next((tmp_path / "issues").glob("*.json")).read_text())
    assert {"title", "body", "labels"} <= payload.keys()


def test_graph_command_prints_mermaid():
    result = CliRunner().invoke(app, ["graph"])
    assert result.exit_code == 0
    assert "route_by_confidence" in result.output
