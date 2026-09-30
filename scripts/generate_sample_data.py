"""Generate the synthetic CI history in sample_data/.

The output is committed, so this script only needs to be re-run when the
scenario changes. It is deterministic (seeded) so regenerated files diff cleanly.

Scenario: 9 CI runs on `main` for a small service with a Java (JUnit 5 /
Surefire) module and a Python (pytest) API test suite. Planted problems:

* Regression   - OrderPricingTest.appliesBulkDiscountAboveThreshold fails from
                 commit 9c41e7a onwards, every run.
* Flaky test   - test_checkout_completes_within_sla fails on timing, and flips
                 pass/fail between reruns of the same commit.
* Environment  - run r1006: database container OOM-killed and DNS failures,
                 breaking unrelated tests in both suites. Gone next run.
* Test-code bug- InventoryClientTest.setUp NPE after a fixture refactor
                 (commit e7a1b52), every run since.
* Ambiguous    - test_export_csv_header_order fails only in the latest run.
"""

from __future__ import annotations

import json
import random
import shutil
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "sample_data"
rng = random.Random(42)

COMMITS = {
    "3f2a9c1": ("checkout: add request tracing headers", "maria.k"),
    "7b8e4d0": ("docs: update API changelog", "sam.o"),
    "9c41e7a": ("pricing: move bulk discount thresholds to config", "dev.patel"),
    "d05b6f3": ("search: tune ranking weights", "lena.w"),
    "e7a1b52": ("test: refactor inventory client fixtures to shared stub server", "tom.r"),
    "f3c9d18": ("reports: stream CSV export in chunks", "maria.k"),
}

# (run_id, commit, trigger)
RUNS = [
    ("r1001", "3f2a9c1", "push"),
    ("r1002", "3f2a9c1", "rerun"),
    ("r1003", "7b8e4d0", "push"),
    ("r1004", "9c41e7a", "push"),
    ("r1005", "9c41e7a", "rerun"),
    ("r1006", "d05b6f3", "push"),
    ("r1007", "e7a1b52", "push"),
    ("r1008", "e7a1b52", "rerun"),
    ("r1009", "f3c9d18", "push"),
]

REGRESSION_RUNS = {"r1004", "r1005", "r1006", "r1007", "r1008", "r1009"}
FLAKY_RUNS = {"r1002", "r1003", "r1007"}
ENV_RUNS = {"r1006"}
TEST_BUG_RUNS = {"r1007", "r1008", "r1009"}
AMBIGUOUS_RUNS = {"r1009"}

JUNIT_FRAMES = """\tat java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:103)
\tat java.base/java.lang.reflect.Method.invoke(Method.java:580)
\tat org.junit.platform.commons.util.ReflectionUtils.invokeMethod(ReflectionUtils.java:728)
\tat org.junit.jupiter.engine.execution.MethodInvocation.proceed(MethodInvocation.java:60)
\tat org.junit.jupiter.engine.execution.InvocationInterceptorChain$ValidatingInvocation.proceed(InvocationInterceptorChain.java:131)"""


@dataclass
class Result:
    kind: str  # "failure" | "error"
    message: str
    text: str
    type: str | None = None


def regression_failure() -> Result:
    msg = "expected: <90.00> but was: <100.00>"
    text = f"""org.opentest4j.AssertionFailedError: {msg}
\tat org.junit.jupiter.api.AssertionFailureBuilder.build(AssertionFailureBuilder.java:151)
\tat org.junit.jupiter.api.AssertionFailureBuilder.buildAndThrow(AssertionFailureBuilder.java:132)
\tat org.junit.jupiter.api.AssertEquals.failNotEqual(AssertEquals.java:197)
\tat org.junit.jupiter.api.AssertEquals.assertEquals(AssertEquals.java:182)
\tat org.junit.jupiter.api.Assertions.assertEquals(Assertions.java:1156)
\tat com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold(OrderPricingTest.java:47)
{JUNIT_FRAMES}"""
    return Result("failure", msg, text, "org.opentest4j.AssertionFailedError")


def npe_setup_error(line: int) -> Result:
    msg = (
        'Cannot invoke "com.example.orders.inventory.StubInventoryServer.baseUrl()" '
        'because "this.stubServer" is null'
    )
    text = f"""java.lang.NullPointerException: {msg}
\tat com.example.orders.inventory.InventoryClientTest.setUp(InventoryClientTest.java:{line})
\tat java.base/java.lang.reflect.Method.invoke(Method.java:580)
\tat org.junit.platform.commons.util.ReflectionUtils.invokeMethod(ReflectionUtils.java:728)
\tat org.junit.jupiter.engine.execution.MethodInvocation.proceed(MethodInvocation.java:60)
\tat org.junit.jupiter.engine.descriptor.ClassBasedTestDescriptor.invokeMethodInExtensionContext(ClassBasedTestDescriptor.java:520)
\tat org.junit.jupiter.engine.descriptor.ClassBasedTestDescriptor.invokeBeforeEachMethods(ClassBasedTestDescriptor.java:504)"""
    return Result("error", msg, text, "java.lang.NullPointerException")


def dns_error(test_method: str, test_line: int) -> Result:
    msg = "rates.internal: Name or service not known"
    text = f"""java.net.UnknownHostException: {msg}
\tat java.base/java.net.Inet6AddressImpl.lookupAllHostAddr(Native Method)
\tat java.base/java.net.InetAddress$PlatformResolver.lookupByName(InetAddress.java:1211)
\tat java.base/java.net.InetAddress.getAllByName0(InetAddress.java:1828)
\tat java.base/java.net.InetAddress.getAllByName(InetAddress.java:1693)
\tat java.base/sun.net.www.http.HttpClient.openServer(HttpClient.java:529)
\tat com.example.orders.shipping.RatesClient.fetchQuote(RatesClient.java:58)
\tat com.example.orders.shipping.ShippingQuoteService.quote(ShippingQuoteService.java:34)
\tat com.example.orders.shipping.ShippingQuoteClientTest.{test_method}(ShippingQuoteClientTest.java:{test_line})
{JUNIT_FRAMES}"""
    return Result("error", msg, text, "java.net.UnknownHostException")


def flaky_failure() -> Result:
    elapsed = rng.uniform(2.05, 2.9)
    req = uuid.UUID(int=rng.getrandbits(128))
    first = f"AssertionError: checkout took {elapsed:.2f}s (request_id={req}), expected < 2.0s"
    msg = f"{first}\nassert {elapsed:.2f} < 2.0"
    text = f"""tests/api/test_checkout.py:38: in test_checkout_completes_within_sla
    assert elapsed < 2.0, f"checkout took {{elapsed:.2f}}s (request_id={{rid}}), expected < 2.0s"
E   {first}
E   assert {elapsed:.2f} < 2.0"""
    return Result("failure", msg, text)


def db_refused(test_file: str, test_name: str, line: int, helper: str) -> Result:
    first = (
        'psycopg.OperationalError: connection failed: connection to server at "10.0.3.12", '
        "port 5432 failed: Connection refused"
    )
    msg = f"{first}\n\tIs the server running on that host and accepting TCP/IP connections?"
    text = f"""{test_file}:{line}: in {test_name}
    {helper}(...)
tests/support/db.py:34: in {helper}
    with get_connection() as conn:
tests/support/db.py:22: in get_connection
    return psycopg.connect(DSN, connect_timeout=3)
.venv/lib/python3.12/site-packages/psycopg/connection.py:119: in connect
    raise last_ex.with_traceback(None)
E   {first}
E   \tIs the server running on that host and accepting TCP/IP connections?"""
    return Result("failure", msg, text)


def csv_header_failure() -> Result:
    first = (
        "AssertionError: assert ['id', 'customer', 'currency', 'total'] == "
        "['id', 'customer', 'total', 'currency']"
    )
    msg = f"{first}\n  At index 2 diff: 'currency' != 'total'"
    text = f"""tests/api/test_reports.py:52: in test_export_csv_header_order
    assert header == ["id", "customer", "total", "currency"]
E   {first}
E     At index 2 diff: 'currency' != 'total'"""
    return Result("failure", msg, text)


def java_cases(run_id: str) -> dict[str, list[tuple[str, Result | None]]]:
    env = run_id in ENV_RUNS
    bug = run_id in TEST_BUG_RUNS
    return {
        "com.example.orders.pricing.OrderPricingTest": [
            (
                "appliesBulkDiscountAboveThreshold",
                regression_failure() if run_id in REGRESSION_RUNS else None,
            ),
            ("noDiscountBelowThreshold", None),
            ("roundsTotalsToTwoDecimals", None),
        ],
        "com.example.orders.inventory.InventoryClientTest": [
            ("reservesStockForOrder", npe_setup_error(31) if bug else None),
            ("releasesStockOnCancel", npe_setup_error(31) if bug else None),
        ],
        "com.example.orders.shipping.ShippingQuoteClientTest": [
            ("quotesStandardShipping", dns_error("quotesStandardShipping", 29) if env else None),
            ("quotesExpressShipping", dns_error("quotesExpressShipping", 41) if env else None),
        ],
        "com.example.orders.api.OrderControllerTest": [
            ("createsOrder", None),
            ("rejectsEmptyCart", None),
        ],
    }


def python_cases(run_id: str) -> list[tuple[str, str, Result | None]]:
    env = run_id in ENV_RUNS
    return [
        (
            "tests.api.test_checkout",
            "test_checkout_completes_within_sla",
            flaky_failure() if run_id in FLAKY_RUNS else None,
        ),
        ("tests.api.test_checkout", "test_checkout_applies_coupon", None),
        (
            "tests.api.test_user_profile",
            "test_get_profile",
            db_refused("tests/api/test_user_profile.py", "test_get_profile", 21, "seed_user")
            if env
            else None,
        ),
        ("tests.api.test_user_profile", "test_update_profile_email", None),
        (
            "tests.api.test_search",
            "test_search_ranking_prefers_exact_match",
            db_refused(
                "tests/api/test_search.py",
                "test_search_ranking_prefers_exact_match",
                17,
                "seed_documents",
            )
            if env
            else None,
        ),
        (
            "tests.api.test_payments",
            "test_refund_payment",
            db_refused("tests/api/test_payments.py", "test_refund_payment", 44, "seed_payment")
            if env
            else None,
        ),
        (
            "tests.api.test_reports",
            "test_export_csv_header_order",
            csv_header_failure() if run_id in AMBIGUOUS_RUNS else None,
        ),
    ]


def add_result(case: ET.Element, result: Result | None) -> None:
    if result is None:
        return
    el = ET.SubElement(case, result.kind, message=result.message)
    if result.type:
        el.set("type", result.type)
    el.text = result.text


def write_xml(root: ET.Element, path: Path) -> None:
    ET.indent(root)
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n")


def write_java_reports(run_dir: Path, run_id: str, ts: datetime) -> list[str]:
    out_dir = run_dir / "orders-service" / "surefire-reports"
    out_dir.mkdir(parents=True)
    summary = []
    for classname, cases in java_cases(run_id).items():
        failures = sum(1 for _, r in cases if r and r.kind == "failure")
        errors = sum(1 for _, r in cases if r and r.kind == "error")
        suite = ET.Element(
            "testsuite",
            name=classname,
            tests=str(len(cases)),
            failures=str(failures),
            errors=str(errors),
            skipped="0",
            time=f"{rng.uniform(0.1, 1.5):.3f}",
            timestamp=ts.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        for name, result in cases:
            case = ET.SubElement(
                suite, "testcase", name=name, classname=classname, time=f"{rng.uniform(0.005, 0.4):.3f}"
            )
            add_result(case, result)
            if result:
                label = "FAILURE" if result.kind == "failure" else "ERROR"
                summary.append(f"[ERROR] {classname}.{name} -- Time elapsed: 0.012 s <<< {label}!")
        write_xml(suite, out_dir / f"TEST-{classname}.xml")
    return summary


def write_python_report(run_dir: Path, run_id: str, ts: datetime) -> list[str]:
    out_dir = run_dir / "api-tests"
    out_dir.mkdir(parents=True)
    cases = python_cases(run_id)
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root,
        "testsuite",
        name="pytest",
        errors="0",
        failures=str(sum(1 for *_, r in cases if r)),
        skipped="0",
        tests=str(len(cases)),
        time=f"{rng.uniform(8, 14):.3f}",
        timestamp=ts.isoformat(),
        hostname=f"ci-runner-{rng.randint(1, 8)}",
    )
    lines = []
    for classname, name, result in cases:
        duration = rng.uniform(2.05, 2.9) if result and "checkout" in name else rng.uniform(0.05, 1.2)
        case = ET.SubElement(suite, "testcase", classname=classname, name=name, time=f"{duration:.3f}")
        add_result(case, result)
        path = classname.replace(".", "/") + ".py"
        lines.append(f"{path}::{name} {'FAILED' if result else 'PASSED'}")
    write_xml(root, out_dir / "pytest-report.xml")
    return lines


def write_console_log(
    run_dir: Path, run_id: str, sha: str, ts: datetime, java: list[str], py: list[str]
) -> None:
    t = ts
    out: list[str] = []

    def log(line: str, step: int = 1) -> None:
        nonlocal t
        t += timedelta(seconds=step)
        out.append(f"{t.strftime('%Y-%m-%dT%H:%M:%SZ')} {line}")

    env = run_id in ENV_RUNS
    log(f"[ci] Run {run_id} on runner ci-runner-{rng.randint(1, 8)}")
    log(f"[ci] Checking out {sha} (main)")
    log("[ci] docker compose up -d db cache rates-stub", 3)
    if env:
        log("[docker] db  | LOG:  database system is ready to accept connections", 8)
        log("[docker] db exited with code 137 (OOMKilled)", 21)
        log("[ci] WARN healthcheck: db unhealthy after 3 retries", 15)
        log("[dns] lookup rates.internal on 127.0.0.11:53: no such host", 2)
    else:
        log("[ci] db is healthy", 12)
    log("[ci] mvn -B -pl orders-service test", 2)
    for line in java:
        log(line, 4)
    log(
        f"[INFO] Tests run: 9, Failures: {sum('FAILURE' in x for x in java)}, "
        f"Errors: {sum('ERROR!' in x for x in java)}, Skipped: 0",
        3,
    )
    log("[ci] pytest tests/api -v --tb=short --junitxml=api-tests/pytest-report.xml", 2)
    for line in py:
        if "test_checkout_completes_within_sla FAILED" in line:
            log(
                f"[app] WARN checkout-service: slow upstream payment-gateway response {rng.randint(1900, 2600)}ms",
                1,
            )
        log(line, 1)
    failed = sum("FAILED" in x for x in py)
    log(f"[ci] ===== {failed} failed, {len(py) - failed} passed =====", 1)
    log("[ci] Job finished: " + ("FAILURE" if (failed or java) else "SUCCESS"), 1)
    (run_dir / "console.log").write_text("\n".join(out) + "\n")


def main() -> None:
    runs_dir = ROOT / "runs"
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
    start = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
    for i, (run_id, sha, trigger) in enumerate(RUNS):
        ts = start + timedelta(hours=9 * i)
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        message, author = COMMITS[sha]
        meta = {
            "run_id": run_id,
            "pipeline": "orders-ci",
            "branch": "main",
            "trigger": trigger,
            "timestamp": ts.isoformat(),
            "commit": {"sha": sha, "message": message, "author": author},
        }
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
        java = write_java_reports(run_dir, run_id, ts)
        py = write_python_report(run_dir, run_id, ts)
        write_console_log(run_dir, run_id, sha, ts, java, py)
    print(f"wrote {len(RUNS)} runs to {runs_dir}")


if __name__ == "__main__":
    main()
