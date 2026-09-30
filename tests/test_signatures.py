import pytest

from ci_triage.models import Outcome, TestResult
from ci_triage.signatures import (
    code_area,
    extract_frames,
    is_test_code_frame,
    normalize_message,
    signature_for,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "checkout took 2.41s (request_id=3f1c2a9e-0b4d-4c55-9a1e-7d2f00c1b2a3), expected < 2.0s",
            "checkout took <N> (request_id=<UUID>), expected < <N>",
        ),
        (
            'connection to server at "10.0.3.12", port 5432 failed',
            'connection to server at "<IP>", port <N> failed',
        ),
        ("deadline at 2026-09-21T10:14:03.512Z exceeded", "deadline at <TS> exceeded"),
        ("object com.acme.Foo@6d06d69c is closed", "object com.acme.Foo@<HEX> is closed"),
        ("pointer 0x7ffee4b2 invalid", "pointer <HEX> invalid"),
        ("wrote /tmp/pytest-of-ci/pytest-3/out.csv", "wrote <TMP>"),
        ("job 9f86d081884c7d65 failed", "job <ID> failed"),
        ("first line\nsecond line", "first line"),
        ("", ""),
    ],
)
def test_normalize_message(raw, expected):
    assert normalize_message(raw) == expected


def test_normalize_keeps_identifiers():
    # Words with digits (service names, error codes) must survive normalization.
    assert normalize_message("http2 stream reset by upstream s3") == "http2 stream reset by upstream s3"


def test_java_frames_skip_framework_and_line_numbers():
    trace = """java.net.UnknownHostException: x
\tat java.base/java.net.InetAddress.getAllByName(InetAddress.java:1693)
\tat com.acme.RatesClient.fetch(RatesClient.java:58)
\tat com.acme.RatesClient.lambda$fetch$0(RatesClient.java:60)
\tat org.junit.platform.commons.util.ReflectionUtils.invokeMethod(ReflectionUtils.java:728)"""
    assert extract_frames(trace, "java") == [
        "com.acme.RatesClient.fetch",
        "com.acme.RatesClient.lambda$fetch",
    ]


def test_python_frames_innermost_first_without_site_packages():
    trace = """tests/api/test_a.py:21: in test_a
    seed()
tests/support/db.py:22: in get_connection
    return psycopg.connect(DSN)
.venv/lib/python3.12/site-packages/psycopg/connection.py:119: in connect
    raise"""
    assert extract_frames(trace, "python") == [
        "tests/support/db.py::get_connection",
        "tests/api/test_a.py::test_a",
    ]


def _result(message, details, name="t", language="python", exc="AssertionError"):
    return TestResult(
        run_id="r",
        commit="c",
        suite="s",
        classname="tests.x",
        name=name,
        language=language,
        outcome=Outcome.FAILED,
        message=message,
        exc_type=exc,
        details=details,
    )


def test_volatile_details_share_a_signature():
    a = _result("took 2.41s (request_id=11111111-1111-1111-1111-111111111111)", "tests/x.py:3: in t")
    b = _result("took 2.87s (request_id=22222222-2222-2222-2222-222222222222)", "tests/x.py:9: in t")
    assert signature_for(a).id == signature_for(b).id


def test_different_frames_split_signatures():
    a = _result("boom", "tests/x.py:3: in t1")
    b = _result("boom", "tests/x.py:3: in t2")
    assert signature_for(a).id != signature_for(b).id


def test_frame_depth_controls_grouping(by_test, runs):
    env = by_test["test_get_profile"]
    assert len(env.tests) == 3  # grouped via the shared helper frame at depth 1
    failures = [
        r
        for run in runs
        for r in run.results
        if r.outcome.is_failure and r.run_id == "r1006" and r.language == "python"
    ]
    assert len({signature_for(f, frame_depth=2).id for f in failures}) == 3


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        ("com.acme.orders.InventoryClientTest.setUp", True),
        ("com.acme.orders.RatesClient.fetch", False),
        ("tests/api/test_checkout.py::test_x", True),
        ("src/app/pricing.py::total", False),
    ],
)
def test_is_test_code_frame(frame, expected):
    assert is_test_code_frame(frame) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("com.example.orders.pricing.OrderPricingTest", "orders/pricing"),
        ("com.example.orders.pricing.OrderPricingTest.appliesDiscount", "orders/pricing"),
        ("tests.api.test_checkout", "api/checkout"),
        ("tests/support/db.py::get_connection", "support/db"),
    ],
)
def test_code_area(value, expected):
    assert code_area(value) == expected
