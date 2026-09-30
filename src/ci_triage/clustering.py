"""Group failures by signature and collect deterministic evidence per group."""

from __future__ import annotations

import re
from collections import defaultdict

from ci_triage.models import ClusterEvidence, Outcome, Run, SuspectCommit, TestHistory, TestResult
from ci_triage.signatures import Signature, code_area, extract_frames, is_test_code_frame, signature_for

INFRA_PATTERNS = {
    "connection refused": re.compile(r"connection refused", re.I),
    "dns resolution failure": re.compile(
        r"name or service not known|no such host|unknownhostexception|temporary failure in name resolution"
        r"|could not resolve host",
        re.I,
    ),
    "container OOM-killed": re.compile(r"oomkilled|exit(?:ed)? (?:with )?code 137|out of memory", re.I),
    "service unhealthy": re.compile(r"unhealthy|service unavailable|\b503\b", re.I),
    "connection timeout": re.compile(r"connect(?:ion)? tim(?:ed )?out|timed out connecting", re.I),
    "disk full": re.compile(r"no space left on device", re.I),
}
_SETUP_MARKERS = re.compile(
    r"\bsetUp\b|\bsetup\b|@Before|BeforeEach|invokeBeforeEachMethods|BeforeAll|failed on setup|fixture", re.I
)
_MAX_LOG_LINES = 8
_MAX_TRACE_LINES = 20


def cluster_failures(
    runs: list[Run], histories: dict[str, TestHistory], frame_depth: int = 1
) -> list[ClusterEvidence]:
    groups: dict[Signature, list[TestResult]] = defaultdict(list)
    for run in runs:
        for r in run.results:
            if r.outcome.is_failure:
                groups[signature_for(r, frame_depth)].append(r)
    clusters = [build_evidence(sig, failures, runs, histories) for sig, failures in groups.items()]
    # Most widespread first, then stable by signature id.
    return sorted(clusters, key=lambda c: (-c.occurrences, c.signature_id))


def build_evidence(
    sig: Signature, failures: list[TestResult], runs: list[Run], histories: dict[str, TestHistory]
) -> ClusterEvidence:
    sample = failures[-1]
    tests = sorted({f.test_id for f in failures})
    failing_runs = sorted({f.run_id for f in failures}, key=[r.meta.run_id for r in runs].index)
    test_histories = [histories[t] for t in tests if t in histories]
    all_frames = extract_frames(sample.details, sample.language)

    text_blob = "\n".join({f"{f.exc_type}: {f.message}\n{f.details}" for f in failures})
    run_logs = {r.meta.run_id: r.log_lines for r in runs}
    failing_log_lines = [line for rid in failing_runs for line in run_logs.get(rid, [])]
    infra = {name for name, pat in INFRA_PATTERNS.items() if pat.search(text_blob)}
    single_run_burst = len(failing_runs) == 1 and len(tests) >= 2
    if infra or single_run_burst:
        # Infra problems usually show up in the job log, not in the test output.
        infra |= {
            name
            for name, pat in INFRA_PATTERNS.items()
            if any(pat.search(line) for line in failing_log_lines)
        }

    since, last_pass, streak = _consistent_streak(test_histories)
    return ClusterEvidence(
        signature_id=sig.id,
        exc_type=sig.exc_type,
        normalized_message=sig.normalized_message,
        top_frames=list(sig.frames),
        sample_message=sample.message.splitlines()[0] if sample.message else "",
        sample_trace=_trim_trace(sample.details),
        language=sample.language,
        tests=tests,
        occurrences=len(failures),
        failing_runs=failing_runs,
        total_runs=len(runs),
        failure_kind="error" if any(f.outcome is Outcome.ERROR for f in failures) else "failure",
        setup_phase=bool(_SETUP_MARKERS.search(sample.details))
        or any(f.message.startswith("failed on setup") for f in failures),
        frames_in_test_code=bool(all_frames) and all(is_test_code_frame(fr) for fr in all_frames),
        infra_signals=sorted(infra),
        single_run_burst=single_run_burst,
        failing_in_latest_run=runs[-1].meta.run_id in failing_runs,
        any_test_flaky=any(h.is_flaky for h in test_histories),
        max_same_commit_flip_rate=max((h.same_commit_flip_rate for h in test_histories), default=0.0),
        consistent_since_commit=since,
        last_passing_commit=last_pass,
        failing_streak=streak,
        suspect_commits=_suspects(runs, last_pass, since),
        code_areas=_areas(all_frames, failures),
        log_excerpt=_log_excerpt(failing_runs, run_logs, failures, bool(infra)),
    )


def _consistent_streak(histories: list[TestHistory]) -> tuple[str | None, str | None, int]:
    """First failing commit shared by all tests in the group (None if they disagree)."""
    if not histories or any(h.is_flaky or not h.failing_since_commit for h in histories):
        return None, None, 0
    since = {h.failing_since_commit for h in histories}
    last = {h.last_passing_commit for h in histories}
    if len(since) != 1 or len(last) != 1:
        return None, None, 0
    return since.pop(), last.pop(), min(h.failing_streak for h in histories)


def _suspects(runs: list[Run], last_pass: str | None, since: str | None) -> list[SuspectCommit]:
    """Commits after the last passing commit up to and including the first failing one."""
    if not since:
        return []
    ordered: list[SuspectCommit] = []
    for run in runs:
        c = run.meta.commit
        if not ordered or ordered[-1].sha != c.sha:
            ordered.append(SuspectCommit(sha=c.sha, message=c.message, author=c.author))
    shas = [c.sha for c in ordered]
    end = shas.index(since)
    start = shas.index(last_pass) + 1 if last_pass in shas else 0
    return ordered[start : end + 1]


def _areas(frames: list[str], failures: list[TestResult]) -> list[str]:
    areas = [code_area(f) for f in frames[:3]] + [code_area(f.classname) for f in failures]
    return list(dict.fromkeys(a for a in areas if a))[:4]


def _log_excerpt(
    failing_runs: list[str], run_logs: dict[str, list[str]], failures: list[TestResult], infra: bool
) -> list[str]:
    names = {f.name for f in failures}
    picked: list[str] = []
    for rid in failing_runs:
        lines = run_logs.get(rid, [])
        for i, line in enumerate(lines):
            hit = any(n in line for n in names) and ("FAIL" in line or "ERROR" in line)
            infra_hit = infra and any(p.search(line) for p in INFRA_PATTERNS.values())
            if hit or infra_hit:
                # Keep a preceding warning: it's often the actual clue (slow upstream, etc.).
                prev = f"[{rid}] {lines[i - 1]}" if i else ""
                if hit and "WARN" in prev and prev not in picked:
                    picked.append(prev)
                if f"[{rid}] {line}" not in picked:
                    picked.append(f"[{rid}] {line}")
        if len(picked) >= _MAX_LOG_LINES:
            break
    return picked[:_MAX_LOG_LINES]


def _trim_trace(details: str) -> str:
    lines = details.strip().splitlines()
    if len(lines) <= _MAX_TRACE_LINES:
        return "\n".join(lines)
    return "\n".join([*lines[:_MAX_TRACE_LINES], f"... ({len(lines) - _MAX_TRACE_LINES} more lines)"])
