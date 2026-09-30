"""Deterministic history analysis: flip rates, streaks and first failing commit."""

from __future__ import annotations

import itertools
from collections import defaultdict

from ci_triage.models import Outcome, Run, RunOutcome, TestHistory


def analyze_history(runs: list[Run]) -> dict[str, TestHistory]:
    """Build a :class:`TestHistory` for every test seen in ``runs`` (oldest run first)."""
    per_test: dict[str, list[RunOutcome]] = defaultdict(list)
    for run in runs:
        for r in run.results:
            if r.outcome is Outcome.SKIPPED:
                continue
            per_test[r.test_id].append(RunOutcome(run_id=r.run_id, commit=r.commit, outcome=r.outcome))
    return {test_id: history_for(test_id, outcomes) for test_id, outcomes in per_test.items()}


def history_for(test_id: str, outcomes: list[RunOutcome]) -> TestHistory:
    failed = [o.outcome.is_failure for o in outcomes]
    n = len(outcomes)

    by_commit: dict[str, list[bool]] = defaultdict(list)
    for o, f in zip(outcomes, failed, strict=True):
        by_commit[o.commit].append(f)
    rerun_commits = [sha for sha, fs in by_commit.items() if len(fs) > 1]
    flipped = [sha for sha in rerun_commits if len(set(by_commit[sha])) > 1]
    flip_rate = len(flipped) / len(rerun_commits) if rerun_commits else 0.0

    transitions = sum(1 for a, b in itertools.pairwise(failed) if a != b)
    streak = trailing_failure_streak(failed)
    failing_since = last_passing = None
    if streak:
        failing_since = outcomes[n - streak].commit
        if streak < n:
            last_passing = outcomes[n - streak - 1].commit

    return TestHistory(
        test_id=test_id,
        outcomes=outcomes,
        executions=n,
        failures=sum(failed),
        fail_rate=round(sum(failed) / n, 3) if n else 0.0,
        commits_with_reruns=len(rerun_commits),
        flipped_commits=flipped,
        same_commit_flip_rate=round(flip_rate, 3),
        transitions=transitions,
        is_flaky=is_flaky(flipped, sum(failed), transitions),
        failing_since_commit=failing_since,
        last_passing_commit=last_passing,
        failing_streak=streak,
    )


def trailing_failure_streak(failed: list[bool]) -> int:
    """Number of consecutive failures at the end of the history."""
    streak = 0
    for f in reversed(failed):
        if not f:
            break
        streak += 1
    return streak


def is_flaky(flipped_commits: list[str], failures: int, transitions: int) -> bool:
    """A test is flaky if it changed outcome on the same commit, or keeps toggling.

    A single failure followed by recovery (P..F..P) is *not* flaky on its own:
    that pattern is more often a one-off environment problem.
    """
    if flipped_commits:
        return True
    return failures >= 2 and transitions >= 3
