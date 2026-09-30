"""Command line entry point: ``triage run --input sample_data --out reports/``."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ci_triage.graph import build_graph
from ci_triage.llm import get_classifier

app = typer.Typer(
    help="Triage CI test failures: flaky tests, regressions, infra problems.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def run(
    input_dir: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        file_okay=False,
        help="Directory with runs/<run_id>/{run.json,*.xml,console.log}.",
    ),
    out: Path = typer.Option(Path("reports"), "--out", "-o", help="Output directory."),
    provider: str = typer.Option(None, help="LLM provider: anthropic | mock (default from env)."),
    model: str = typer.Option(None, help="Model id (default: $LLM_MODEL or claude-sonnet-5-5)."),
    threshold: float = typer.Option(0.7, help="Confidence below this goes to human review."),
    frame_depth: int = typer.Option(1, help="In-app stack frames included in the signature."),
    dry_run: bool = typer.Option(
        True, "--dry-run/--no-dry-run", help="Only write issue payloads; --no-dry-run files GitHub issues."
    ),
    repo: str = typer.Option(None, help="GitHub repo (owner/name) for issue filing."),
) -> None:
    """Run the triage pipeline and write the report."""
    try:
        classifier = get_classifier(provider, model)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--provider") from exc
    graph = build_graph(classifier)
    state = graph.invoke(
        {
            "input_dir": str(input_dir),
            "confidence_threshold": threshold,
            "frame_depth": frame_depth,
            "dry_run": dry_run,
            "repo": repo,
        }
    )

    out.mkdir(parents=True, exist_ok=True)
    (out / "triage-report.md").write_text(state["report_markdown"])
    items = state.get("items", [])
    (out / "triage.json").write_text(json.dumps([i.model_dump(mode="json") for i in items], indent=2) + "\n")

    drafts = state.get("bug_drafts", [])
    for sub, ext in (("bugs", "md"), ("issues", "json")):
        (out / sub).mkdir(exist_ok=True)
        for stale in (out / sub).glob(f"*.{ext}"):
            stale.unlink()
    for d in drafts:
        (out / "bugs" / f"{d.signature_id}.md").write_text(f"# {d.title}\n\n{d.body}")
        (out / "issues" / f"{d.signature_id}.json").write_text(d.model_dump_json(indent=2) + "\n")

    typer.echo(f"classifier: {classifier.name}")
    typer.echo(
        f"runs: {len(state['runs'])}  signatures: {len(items)}  "
        f"needs review: {sum(i.needs_review for i in items)}"
    )
    for i in items:
        c = i.classification
        flag = "  [review]" if i.needs_review else ""
        typer.echo(
            f"  {i.evidence.signature_id}  {c.category:<14} {c.confidence:.2f}  "
            f"{len(i.evidence.tests)} test(s){flag}"
        )
    for r in state.get("issue_results", []):
        where = r.url or (out / "issues" / f"{r.signature_id}.json")
        typer.echo(f"  issue {r.signature_id}: {r.status} {where} {r.detail}".rstrip())
    typer.echo(f"report: {out / 'triage-report.md'}")


@app.command()
def graph() -> None:
    """Print the pipeline graph as Mermaid."""
    from ci_triage.llm import MockClassifier

    typer.echo(build_graph(MockClassifier()).get_graph().draw_mermaid())


if __name__ == "__main__":
    app()
