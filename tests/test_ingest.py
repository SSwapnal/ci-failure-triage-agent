import textwrap

from ci_triage.ingest import parse_junit_xml
from ci_triage.models import Outcome

SUREFIRE = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.acme.FooTest" tests="3" failures="1" errors="1" skipped="1">
  <testcase name="passes" classname="com.acme.FooTest" time="0.01"/>
  <testcase name="fails" classname="com.acme.FooTest" time="0.02">
    <failure message="expected: &lt;1&gt; but was: &lt;2&gt;" type="org.opentest4j.AssertionFailedError">trace
\tat com.acme.FooTest.fails(FooTest.java:12)</failure>
  </testcase>
  <testcase name="explodes" classname="com.acme.FooTest" time="0.00">
    <error message="boom" type="java.lang.IllegalStateException">java.lang.IllegalStateException: boom</error>
  </testcase>
  <testcase name="ignored" classname="com.acme.FooTest"><skipped/></testcase>
</testsuite>
"""

PYTEST = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="1" failures="1">
  <testcase classname="tests.test_x" name="test_y" time="0.5">
    <failure message="ValueError: bad input&#10;more">tests/test_x.py:3: in test_y
E   ValueError: bad input</failure>
  </testcase>
</testsuite></testsuites>
"""


def test_parses_surefire_outcomes(tmp_path):
    path = tmp_path / "TEST-com.acme.FooTest.xml"
    path.write_text(SUREFIRE)
    results = {r.name: r for r in parse_junit_xml(path, "r1", "abc")}

    assert results["passes"].outcome is Outcome.PASSED
    assert results["fails"].outcome is Outcome.FAILED
    assert results["fails"].exc_type == "org.opentest4j.AssertionFailedError"
    assert results["fails"].message == "expected: <1> but was: <2>"
    assert results["explodes"].outcome is Outcome.ERROR
    assert results["ignored"].outcome is Outcome.SKIPPED
    assert all(r.language == "java" for r in results.values())
    assert results["fails"].test_id == "com.acme.FooTest::fails"


def test_parses_pytest_and_splits_exception_type(tmp_path):
    path = tmp_path / "pytest.xml"
    path.write_text(textwrap.dedent(PYTEST))
    [r] = parse_junit_xml(path, "r1", "abc")

    assert r.language == "python"
    assert r.exc_type == "ValueError"
    assert r.message.startswith("bad input")
    assert r.duration == 0.5


def test_loads_sample_runs_in_time_order(runs):
    assert [r.meta.run_id for r in runs] == [f"r100{i}" for i in range(1, 10)]
    assert all(len(r.results) == 16 for r in runs)
    assert all(r.log_lines for r in runs)
    assert runs[3].meta.commit.sha == "9c41e7a"
