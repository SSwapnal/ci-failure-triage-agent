"""Load CI runs: run metadata, JUnit XML reports and console logs.

Expected layout (one directory per CI run, any nesting for reports):

    <input>/runs/<run_id>/run.json
    <input>/runs/<run_id>/**/*.xml        JUnit XML (Surefire, pytest, ...)
    <input>/runs/<run_id>/console.log     optional
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from junitparser import Error, Failure, JUnitXml, Skipped, TestSuite

from ci_triage.models import Outcome, Run, RunMeta, TestResult

_PY_EXC_PREFIX = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Failure|Warning)):\s?(.*)$", re.S
)


def load_runs(input_dir: str | Path) -> list[Run]:
    """Load every run under ``input_dir/runs``, oldest first."""
    root = Path(input_dir)
    runs_root = root / "runs" if (root / "runs").is_dir() else root
    runs = [load_run(meta.parent) for meta in sorted(runs_root.glob("*/run.json"))]
    if not runs:
        raise FileNotFoundError(f"no */run.json found under {runs_root}")
    return sorted(runs, key=lambda r: r.meta.timestamp)


def load_run(run_dir: Path) -> Run:
    meta = RunMeta.model_validate(json.loads((run_dir / "run.json").read_text()))
    results: list[TestResult] = []
    for xml_path in sorted(run_dir.rglob("*.xml")):
        results.extend(parse_junit_xml(xml_path, meta.run_id, meta.commit.sha))
    log_path = run_dir / "console.log"
    log_lines = log_path.read_text(errors="replace").splitlines() if log_path.exists() else []
    return Run(meta=meta, results=results, log_lines=log_lines)


def parse_junit_xml(path: Path, run_id: str, commit: str) -> list[TestResult]:
    """Parse a JUnit XML file (single <testsuite> or <testsuites>) into results."""
    xml = JUnitXml.fromfile(str(path))
    suites = [xml] if isinstance(xml, TestSuite) else list(xml)
    results = []
    for suite in suites:
        for case in suite:
            results.append(_to_result(case, suite.name or path.stem, run_id, commit))
    return results


def _to_result(case, suite_name: str, run_id: str, commit: str) -> TestResult:
    outcome, message, exc_type, details = Outcome.PASSED, "", "", ""
    for res in case.result:
        if isinstance(res, (Failure, Error)):
            outcome = Outcome.FAILED if isinstance(res, Failure) else Outcome.ERROR
            message = res.message or ""
            exc_type = res.type or ""
            details = res.text or ""
            break
        if isinstance(res, Skipped):
            outcome = Outcome.SKIPPED

    language = _detect_language(suite_name, case.classname or "", details)
    if outcome.is_failure and not exc_type:
        # pytest puts "ExcType: message" into the message attribute instead of `type`.
        m = _PY_EXC_PREFIX.match(message)
        if m:
            exc_type, message = m.group(1), m.group(2)
    return TestResult(
        run_id=run_id,
        commit=commit,
        suite=suite_name,
        classname=case.classname or suite_name,
        name=case.name,
        language=language,
        outcome=outcome,
        duration=float(case.time or 0.0),
        message=message.strip(),
        exc_type=exc_type,
        details=details,
    )


def _detect_language(suite_name: str, classname: str, details: str) -> str:
    if suite_name == "pytest" or ".py:" in details or classname.split(".")[-1].startswith("test_"):
        return "python"
    return "java"
