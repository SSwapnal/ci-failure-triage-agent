"""Markdown rendering: triage summary and bug-report drafts."""

from __future__ import annotations

import re

from ci_triage.models import BugDraft, Run, TestHistory, TriageItem

CATEGORY_TITLES = {
    "product_bug": "Product bugs",
    "test_code_bug": "Test-code bugs",
    "flaky_test": "Flaky tests",
    "environment": "Environment / infrastructure",
}
ACTIONS = {
    "product_bug": "File bug (draft below)",
    "test_code_bug": "File bug for test owners (draft below)",
    "flaky_test": "Quarantine + stabilise",
    "environment": "Infra follow-up, rerun",
}
BUG_CATEGORIES = ("product_bug", "test_code_bug")


def short_test(test_id: str) -> str:
    classname, name = test_id.split("::")
    return f"{classname.rsplit('.', 1)[-1]}.{name}"


def repro_command(test_id: str, language: str) -> str:
    classname, name = test_id.split("::")
    if language == "python":
        return f'pytest "{classname.replace(".", "/")}.py::{name}"'
    return f"mvn -Dtest={classname.rsplit('.', 1)[-1]}#{name} test"


def bug_drafts(items: list[TriageItem]) -> list[BugDraft]:
    return [
        render_bug_draft(i)
        for i in items
        if i.classification.category in BUG_CATEGORIES and not i.needs_review
    ]


def render_bug_draft(item: TriageItem) -> BugDraft:
    e, c = item.evidence, item.classification
    exc = e.exc_type.rsplit(".", 1)[-1]
    first_test = short_test(e.tests[0]) + (f" (+{len(e.tests) - 1} more)" if len(e.tests) > 1 else "")
    title = f"{first_test}: {exc}: {e.sample_message}"
    if len(title) > 120:
        title = title[:117] + "..."

    suspect = next((s for s in e.suspect_commits if s.sha == c.suspected_commit), None)
    suspect_line = (
        f"`{suspect.sha}` {suspect.message} ({suspect.author})"
        if suspect
        else f"`{c.suspected_commit}`"
        if c.suspected_commit
        else "not determined"
    )
    tests = "\n".join(f"- `{t}`" for t in e.tests)
    repro = "\n".join(f"    {repro_command(t, e.language)}" for t in e.tests)
    logs = "\n".join(e.log_excerpt) or "(no matching log lines)"

    body = f"""**Category:** {c.category} | **Confidence:** {c.confidence:.2f} | **Suggested owner:** {c.suggested_owner_area}
**Suspected commit:** {suspect_line}

### Summary
{c.rationale}

### Affected tests
{tests}

### Reproduction
- Last passing commit: `{e.last_passing_commit or "n/a"}`
- First failing commit: `{e.consistent_since_commit or "n/a"}`
- Failing in {len(e.failing_runs)}/{e.total_runs} analysed runs: {", ".join(e.failing_runs)}

```
{repro}
```

### Evidence
- Signature: `{e.exc_type}` / `{e.normalized_message}` / top frame `{", ".join(e.top_frames) or "n/a"}`
- Failure kind: {e.failure_kind}; raised during setup: {"yes" if e.setup_phase else "no"}
- Same-commit flip rate: {e.max_same_commit_flip_rate:.2f}; infra signals: {", ".join(e.infra_signals) or "none"}

### Failure output (excerpt)
```text
{e.sample_trace}
```

### CI log excerpt
```text
{logs}
```

<!-- triage-signature: {e.signature_id} -->
"""
    labels = ["ci-triage", c.category.replace("_", "-")]
    return BugDraft(signature_id=e.signature_id, title=title, body=body, labels=labels)


def render_report(
    runs: list[Run],
    items: list[TriageItem],
    histories: dict[str, TestHistory],
    classifier_name: str,
    threshold: float,
) -> str:
    first, last = runs[0].meta, runs[-1].meta
    total_failures = sum(i.evidence.occurrences for i in items)
    lines = [
        "# CI Failure Triage Report",
        "",
        f"- **Runs analysed:** {len(runs)} on `{last.branch}` ({first.run_id} to {last.run_id}, "
        f"{first.timestamp:%Y-%m-%d} to {last.timestamp:%Y-%m-%d})",
        f"- **Latest run:** {last.run_id} at `{last.commit.sha}` ({last.commit.message})",
        f"- **Failures:** {total_failures} test failures grouped into {len(items)} signatures",
        f"- **Classifier:** {classifier_name}; items below confidence {threshold:.2f} go to human review",
        "",
        "## Summary",
        "",
        "| Signature | Category | Tests | Failing runs | Latest run | Confidence | Action |",
        "|---|---|---|---|---|---|---|",
    ]
    for i in items:
        e, c = i.evidence, i.classification
        action = "Needs human review" if i.needs_review else ACTIONS[c.category]
        lines.append(
            f"| `{e.signature_id}` | {c.category} | {len(e.tests)} | {len(e.failing_runs)}/{e.total_runs} "
            f"| {'fail' if e.failing_in_latest_run else 'pass'} | {c.confidence:.2f} | {action} |"
        )

    for category, title in CATEGORY_TITLES.items():
        group = [i for i in items if i.classification.category == category and not i.needs_review]
        lines += ["", f"## {title}", ""]
        if not group:
            lines.append("None.")
        for i in group:
            lines += _item_section(i)

    review = [i for i in items if i.needs_review]
    lines += ["", "## Needs human review", ""]
    if not review:
        lines.append("None.")
    for i in review:
        lines += _item_section(i, show_category=True)

    lines += [
        "",
        "## Test history (tests with at least one failure)",
        "",
        "| Test | Runs | Failures | Fail rate | Same-commit flip rate | Flaky | Failing since |",
        "|---|---|---|---|---|---|---|",
    ]
    for h in sorted(histories.values(), key=lambda h: (-h.failures, h.test_id)):
        if h.failures:
            lines.append(
                f"| `{short_test(h.test_id)}` | {h.executions} | {h.failures} | {h.fail_rate:.2f} "
                f"| {h.same_commit_flip_rate:.2f} ({len(h.flipped_commits)}/{h.commits_with_reruns} commits) "
                f"| {'yes' if h.is_flaky else 'no'} | {h.failing_since_commit or '-'} |"
            )

    drafts = bug_drafts(items)
    lines += ["", "## Bug report drafts", ""]
    if not drafts:
        lines.append("None.")
    for d in drafts:
        lines += [f"### {d.title}", "", d.body.rstrip(), ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip() + "\n"


def _item_section(item: TriageItem, show_category: bool = False) -> list[str]:
    e, c = item.evidence, item.classification
    tests = ", ".join(f"`{short_test(t)}`" for t in e.tests)
    out = [
        f"### `{e.signature_id}` {e.exc_type.rsplit('.', 1)[-1]}: {e.sample_message[:100]}",
        "",
    ]
    if show_category:
        out.append(f"- **Proposed category:** {c.category} (confidence {c.confidence:.2f})")
    else:
        out.append(f"- **Confidence:** {c.confidence:.2f}")
    out += [
        f"- **Tests:** {tests}",
        f"- **Failing runs:** {', '.join(e.failing_runs)} ({len(e.failing_runs)}/{e.total_runs})",
        f"- **Owner area:** {c.suggested_owner_area}",
    ]
    if c.suspected_commit:
        out.append(f"- **Suspected commit:** `{c.suspected_commit}`")
    if e.infra_signals:
        out.append(f"- **Infra signals:** {', '.join(e.infra_signals)}")
    out += [f"- **Rationale:** {c.rationale}", ""]
    return out
