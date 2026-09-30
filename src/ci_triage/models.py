"""Data models shared across the pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"  # assertion failure
    ERROR = "error"  # unexpected exception (JUnit <error>)
    SKIPPED = "skipped"

    @property
    def is_failure(self) -> bool:
        return self in (Outcome.FAILED, Outcome.ERROR)


class Commit(BaseModel):
    sha: str
    message: str = ""
    author: str = ""


class RunMeta(BaseModel):
    run_id: str
    commit: Commit
    branch: str = "main"
    timestamp: datetime
    pipeline: str = ""
    trigger: str = ""


class TestResult(BaseModel):
    __test__ = False  # not a pytest test class

    run_id: str
    commit: str
    suite: str
    classname: str
    name: str
    language: Literal["java", "python"]
    outcome: Outcome
    duration: float = 0.0
    message: str = ""
    exc_type: str = ""
    details: str = ""

    @property
    def test_id(self) -> str:
        return f"{self.classname}::{self.name}"


class Run(BaseModel):
    meta: RunMeta
    results: list[TestResult]
    log_lines: list[str] = Field(default_factory=list)


class RunOutcome(BaseModel):
    run_id: str
    commit: str
    outcome: Outcome


class TestHistory(BaseModel):
    """Deterministic history for one test across all ingested runs."""

    __test__ = False

    test_id: str
    outcomes: list[RunOutcome]
    executions: int
    failures: int
    fail_rate: float
    commits_with_reruns: int
    flipped_commits: list[str]
    same_commit_flip_rate: float
    transitions: int
    is_flaky: bool
    failing_since_commit: str | None = None
    last_passing_commit: str | None = None
    failing_streak: int = 0


class SuspectCommit(BaseModel):
    sha: str
    message: str
    author: str


class ClusterEvidence(BaseModel):
    """Everything the classifier gets to see about one failure group."""

    signature_id: str
    exc_type: str
    normalized_message: str
    top_frames: list[str]
    sample_message: str
    sample_trace: str
    language: str
    tests: list[str]
    occurrences: int
    failing_runs: list[str]
    total_runs: int
    failure_kind: str
    setup_phase: bool
    frames_in_test_code: bool
    infra_signals: list[str]
    single_run_burst: bool
    failing_in_latest_run: bool
    any_test_flaky: bool
    max_same_commit_flip_rate: float
    consistent_since_commit: str | None
    last_passing_commit: str | None
    failing_streak: int
    suspect_commits: list[SuspectCommit]
    code_areas: list[str]
    log_excerpt: list[str]


Category = Literal["product_bug", "flaky_test", "environment", "test_code_bug"]


class Classification(BaseModel):
    """Structured output requested from the LLM for each cluster."""

    category: Category = Field(description="Root-cause category of the failure group.")
    confidence: float = Field(description="Confidence between 0.0 and 1.0.")
    rationale: str = Field(description="Two to four sentences citing the evidence used.")
    suspected_commit: str | None = Field(
        default=None, description="Short sha of the commit most likely responsible, if any."
    )
    suggested_owner_area: str = Field(description="Code area or team that should own the fix.")

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class TriageItem(BaseModel):
    evidence: ClusterEvidence
    classification: Classification
    needs_review: bool = False


class BugDraft(BaseModel):
    signature_id: str
    title: str
    body: str
    labels: list[str]


class IssueResult(BaseModel):
    signature_id: str
    status: Literal["dry-run", "created", "exists", "error"]
    url: str | None = None
    detail: str = ""
