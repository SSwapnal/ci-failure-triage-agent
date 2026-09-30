"""LangGraph pipeline wiring.

ingest -> analyze_history -> cluster -> classify -> route -> report -> file_issues
Deterministic steps come first; the LLM only sees pre-computed evidence.
"""

from __future__ import annotations

import os
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ci_triage.clustering import cluster_failures
from ci_triage.flakiness import analyze_history
from ci_triage.ingest import load_runs
from ci_triage.issues import file_issues
from ci_triage.llm import Classifier
from ci_triage.models import (
    BugDraft,
    ClusterEvidence,
    IssueResult,
    Run,
    TestHistory,
    TriageItem,
)
from ci_triage.report import bug_drafts, render_report


class TriageState(TypedDict, total=False):
    # inputs
    input_dir: str
    confidence_threshold: float
    frame_depth: int
    dry_run: bool
    repo: str | None
    # produced by nodes
    runs: list[Run]
    histories: dict[str, TestHistory]
    clusters: list[ClusterEvidence]
    items: list[TriageItem]
    report_markdown: str
    bug_drafts: list[BugDraft]
    issue_results: list[IssueResult]


def build_graph(classifier: Classifier):
    def ingest(state: TriageState) -> TriageState:
        return {"runs": load_runs(state["input_dir"])}

    def analyze(state: TriageState) -> TriageState:
        return {"histories": analyze_history(state["runs"])}

    def cluster(state: TriageState) -> TriageState:
        depth = state.get("frame_depth", 1)
        return {"clusters": cluster_failures(state["runs"], state["histories"], depth)}

    def classify(state: TriageState) -> TriageState:
        items = [TriageItem(evidence=c, classification=classifier.classify(c)) for c in state["clusters"]]
        return {"items": items}

    def route(state: TriageState) -> TriageState:
        threshold = state.get("confidence_threshold", 0.7)
        items = [
            i.model_copy(update={"needs_review": i.classification.confidence < threshold})
            for i in state["items"]
        ]
        return {"items": items}

    def report(state: TriageState) -> TriageState:
        items = state.get("items", [])
        markdown = render_report(
            state["runs"], items, state["histories"], classifier.name, state.get("confidence_threshold", 0.7)
        )
        return {"report_markdown": markdown, "bug_drafts": bug_drafts(items)}

    def issues(state: TriageState) -> TriageState:
        results = file_issues(
            state["bug_drafts"],
            repo=state.get("repo"),
            token=os.environ.get("GITHUB_TOKEN"),
            dry_run=state.get("dry_run", True),
        )
        return {"issue_results": results}

    g = StateGraph(TriageState)
    g.add_node("ingest", ingest)
    g.add_node("analyze_history", analyze)
    g.add_node("cluster", cluster)
    g.add_node("classify", classify)
    g.add_node("route_by_confidence", route)
    g.add_node("report", report)
    g.add_node("file_issues", issues)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "analyze_history")
    g.add_edge("analyze_history", "cluster")
    g.add_conditional_edges(
        "cluster", lambda s: "classify" if s["clusters"] else "report", ["classify", "report"]
    )
    g.add_edge("classify", "route_by_confidence")
    g.add_edge("route_by_confidence", "report")
    g.add_conditional_edges(
        "report", lambda s: "file_issues" if s["bug_drafts"] else END, ["file_issues", END]
    )
    g.add_edge("file_issues", END)
    return g.compile()
