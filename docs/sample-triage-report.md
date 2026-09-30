# CI Failure Triage Report

- **Runs analysed:** 9 on `main` (r1001 to r1009, 2026-09-21 to 2026-09-24)
- **Latest run:** r1009 at `f3c9d18` (reports: stream CSV export in chunks)
- **Failures:** 21 test failures grouped into 6 signatures
- **Classifier:** mock; items below confidence 0.70 go to human review

## Summary

| Signature | Category | Tests | Failing runs | Latest run | Confidence | Action |
|---|---|---|---|---|---|---|
| `96c4992c80` | product_bug | 1 | 6/9 | fail | 0.85 | File bug (draft below) |
| `a8252e02cf` | test_code_bug | 2 | 3/9 | fail | 0.85 | File bug for test owners (draft below) |
| `af8af61825` | flaky_test | 1 | 3/9 | pass | 0.80 | Quarantine + stabilise |
| `eacf7aa34b` | environment | 3 | 1/9 | pass | 0.90 | Infra follow-up, rerun |
| `3f511f3805` | environment | 2 | 1/9 | pass | 0.90 | Infra follow-up, rerun |
| `08f85f9f62` | product_bug | 1 | 1/9 | fail | 0.55 | Needs human review |

## Product bugs

### `96c4992c80` AssertionFailedError: expected: <90.00> but was: <100.00>

- **Confidence:** 0.85
- **Tests:** `OrderPricingTest.appliesBulkDiscountAboveThreshold`
- **Failing runs:** r1004, r1005, r1006, r1007, r1008, r1009 (6/9)
- **Owner area:** orders/pricing
- **Suspected commit:** `9c41e7a`
- **Rationale:** Passed through 7b8e4d0 and failed in all 6 runs since 9c41e7a, with no same-commit flips and no infra signals. The assertion on a business value ('expected: <90.00> but was: <100.00>') points at 9c41e7a ('pricing: move bulk discount thresholds to config').

## Test-code bugs

### `a8252e02cf` NullPointerException: Cannot invoke "com.example.orders.inventory.StubInventoryServer.baseUrl()" because "this.stubServer"

- **Confidence:** 0.85
- **Tests:** `InventoryClientTest.releasesStockOnCancel`, `InventoryClientTest.reservesStockForOrder`
- **Failing runs:** r1007, r1008, r1009 (3/9)
- **Owner area:** orders/inventory
- **Suspected commit:** `e7a1b52`
- **Rationale:** java.lang.NullPointerException raised in test code (com.example.orders.inventory.InventoryClientTest.setUp) during setup, failing every run since e7a1b52 ('test: refactor inventory client fixtures to shared stub server'). The error is in the test harness before the product code is exercised, so this is a test-code problem.

## Flaky tests

### `af8af61825` AssertionError: checkout took 2.52s (request_id=122c9a56-01d7-4256-3860-2ab696a402f2), expected < 2.0s

- **Confidence:** 0.80
- **Tests:** `test_checkout.test_checkout_completes_within_sla`
- **Failing runs:** r1002, r1003, r1007 (3/9)
- **Owner area:** api/checkout
- **Rationale:** Failed in 3/9 runs and changed outcome between reruns of the same commit (flip rate 0.67). Failure message: 'checkout took <N> (request_id=<UUID>), expected < <N>'. A test that changes outcome without a code change should be stabilised or quarantined, not filed as a product bug.

## Environment / infrastructure

### `eacf7aa34b` OperationalError: connection failed: connection to server at "10.0.3.12", port 5432 failed: Connection refused

- **Confidence:** 0.90
- **Tests:** `test_payments.test_refund_payment`, `test_search.test_search_ranking_prefers_exact_match`, `test_user_profile.test_get_profile`
- **Failing runs:** r1006 (1/9)
- **Owner area:** ci-infrastructure
- **Infra signals:** connection refused, container OOM-killed, dns resolution failure, service unhealthy
- **Rationale:** 3 test(s) failed only in r1006 with infra signals (connection refused, container OOM-killed, dns resolution failure, service unhealthy). The tests pass again in later runs without a code change, which points at CI infrastructure rather than the product.

### `3f511f3805` UnknownHostException: rates.internal: Name or service not known

- **Confidence:** 0.90
- **Tests:** `ShippingQuoteClientTest.quotesExpressShipping`, `ShippingQuoteClientTest.quotesStandardShipping`
- **Failing runs:** r1006 (1/9)
- **Owner area:** ci-infrastructure
- **Infra signals:** container OOM-killed, dns resolution failure, service unhealthy
- **Rationale:** 2 test(s) failed only in r1006 with infra signals (container OOM-killed, dns resolution failure, service unhealthy). The tests pass again in later runs without a code change, which points at CI infrastructure rather than the product.

## Needs human review

### `08f85f9f62` AssertionError: assert ['id', 'customer', 'currency', 'total'] == ['id', 'customer', 'total', 'currency']

- **Proposed category:** product_bug (confidence 0.55)
- **Tests:** `test_reports.test_export_csv_header_order`
- **Failing runs:** r1009 (1/9)
- **Owner area:** api/reports
- **Suspected commit:** `f3c9d18`
- **Rationale:** New failure seen only once, in the latest run on f3c9d18 ('reports: stream CSV export in chunks'). A single observation cannot distinguish a regression from a flaky failure; rerun to confirm before filing.

## Test history (tests with at least one failure)

| Test | Runs | Failures | Fail rate | Same-commit flip rate | Flaky | Failing since |
|---|---|---|---|---|---|---|
| `OrderPricingTest.appliesBulkDiscountAboveThreshold` | 9 | 6 | 0.67 | 0.00 (0/3 commits) | no | 9c41e7a |
| `InventoryClientTest.releasesStockOnCancel` | 9 | 3 | 0.33 | 0.00 (0/3 commits) | no | e7a1b52 |
| `InventoryClientTest.reservesStockForOrder` | 9 | 3 | 0.33 | 0.00 (0/3 commits) | no | e7a1b52 |
| `test_checkout.test_checkout_completes_within_sla` | 9 | 3 | 0.33 | 0.67 (2/3 commits) | yes | - |
| `ShippingQuoteClientTest.quotesExpressShipping` | 9 | 1 | 0.11 | 0.00 (0/3 commits) | no | - |
| `ShippingQuoteClientTest.quotesStandardShipping` | 9 | 1 | 0.11 | 0.00 (0/3 commits) | no | - |
| `test_payments.test_refund_payment` | 9 | 1 | 0.11 | 0.00 (0/3 commits) | no | - |
| `test_reports.test_export_csv_header_order` | 9 | 1 | 0.11 | 0.00 (0/3 commits) | no | f3c9d18 |
| `test_search.test_search_ranking_prefers_exact_match` | 9 | 1 | 0.11 | 0.00 (0/3 commits) | no | - |
| `test_user_profile.test_get_profile` | 9 | 1 | 0.11 | 0.00 (0/3 commits) | no | - |

## Bug report drafts

### OrderPricingTest.appliesBulkDiscountAboveThreshold: AssertionFailedError: expected: <90.00> but was: <100.00>

**Category:** product_bug | **Confidence:** 0.85 | **Suggested owner:** orders/pricing
**Suspected commit:** `9c41e7a` pricing: move bulk discount thresholds to config (dev.patel)

### Summary
Passed through 7b8e4d0 and failed in all 6 runs since 9c41e7a, with no same-commit flips and no infra signals. The assertion on a business value ('expected: <90.00> but was: <100.00>') points at 9c41e7a ('pricing: move bulk discount thresholds to config').

### Affected tests
- `com.example.orders.pricing.OrderPricingTest::appliesBulkDiscountAboveThreshold`

### Reproduction
- Last passing commit: `7b8e4d0`
- First failing commit: `9c41e7a`
- Failing in 6/9 analysed runs: r1004, r1005, r1006, r1007, r1008, r1009

```
    mvn -Dtest=OrderPricingTest#appliesBulkDiscountAboveThreshold test
```

### Evidence
- Signature: `org.opentest4j.AssertionFailedError` / `expected: <<N>> but was: <<N>>` / top frame `com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold`
- Failure kind: failure; raised during setup: no
- Same-commit flip rate: 0.00; infra signals: none

### Failure output (excerpt)
```text
org.opentest4j.AssertionFailedError: expected: <90.00> but was: <100.00>
	at org.junit.jupiter.api.AssertionFailureBuilder.build(AssertionFailureBuilder.java:151)
	at org.junit.jupiter.api.AssertionFailureBuilder.buildAndThrow(AssertionFailureBuilder.java:132)
	at org.junit.jupiter.api.AssertEquals.failNotEqual(AssertEquals.java:197)
	at org.junit.jupiter.api.AssertEquals.assertEquals(AssertEquals.java:182)
	at org.junit.jupiter.api.Assertions.assertEquals(Assertions.java:1156)
	at com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold(OrderPricingTest.java:47)
	at java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:103)
	at java.base/java.lang.reflect.Method.invoke(Method.java:580)
	at org.junit.platform.commons.util.ReflectionUtils.invokeMethod(ReflectionUtils.java:728)
	at org.junit.jupiter.engine.execution.MethodInvocation.proceed(MethodInvocation.java:60)
	at org.junit.jupiter.engine.execution.InvocationInterceptorChain$ValidatingInvocation.proceed(InvocationInterceptorChain.java:131)
```

### CI log excerpt
```text
[r1004] 2026-09-22T12:00:23Z [ERROR] com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold -- Time elapsed: 0.012 s <<< FAILURE!
[r1005] 2026-09-22T21:00:23Z [ERROR] com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold -- Time elapsed: 0.012 s <<< FAILURE!
[r1006] 2026-09-23T06:00:57Z [ERROR] com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold -- Time elapsed: 0.012 s <<< FAILURE!
[r1007] 2026-09-23T15:00:23Z [ERROR] com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold -- Time elapsed: 0.012 s <<< FAILURE!
[r1008] 2026-09-24T00:00:23Z [ERROR] com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold -- Time elapsed: 0.012 s <<< FAILURE!
[r1009] 2026-09-24T09:00:23Z [ERROR] com.example.orders.pricing.OrderPricingTest.appliesBulkDiscountAboveThreshold -- Time elapsed: 0.012 s <<< FAILURE!
```

<!-- triage-signature: 96c4992c80 -->

### InventoryClientTest.releasesStockOnCancel (+1 more): NullPointerException: Cannot invoke "com.example.orders.inventor...

**Category:** test_code_bug | **Confidence:** 0.85 | **Suggested owner:** orders/inventory
**Suspected commit:** `e7a1b52` test: refactor inventory client fixtures to shared stub server (tom.r)

### Summary
java.lang.NullPointerException raised in test code (com.example.orders.inventory.InventoryClientTest.setUp) during setup, failing every run since e7a1b52 ('test: refactor inventory client fixtures to shared stub server'). The error is in the test harness before the product code is exercised, so this is a test-code problem.

### Affected tests
- `com.example.orders.inventory.InventoryClientTest::releasesStockOnCancel`
- `com.example.orders.inventory.InventoryClientTest::reservesStockForOrder`

### Reproduction
- Last passing commit: `d05b6f3`
- First failing commit: `e7a1b52`
- Failing in 3/9 analysed runs: r1007, r1008, r1009

```
    mvn -Dtest=InventoryClientTest#releasesStockOnCancel test
    mvn -Dtest=InventoryClientTest#reservesStockForOrder test
```

### Evidence
- Signature: `java.lang.NullPointerException` / `Cannot invoke "com.example.orders.inventory.StubInventoryServer.baseUrl()" because "this.stubServer" is null` / top frame `com.example.orders.inventory.InventoryClientTest.setUp`
- Failure kind: error; raised during setup: yes
- Same-commit flip rate: 0.00; infra signals: none

### Failure output (excerpt)
```text
java.lang.NullPointerException: Cannot invoke "com.example.orders.inventory.StubInventoryServer.baseUrl()" because "this.stubServer" is null
	at com.example.orders.inventory.InventoryClientTest.setUp(InventoryClientTest.java:31)
	at java.base/java.lang.reflect.Method.invoke(Method.java:580)
	at org.junit.platform.commons.util.ReflectionUtils.invokeMethod(ReflectionUtils.java:728)
	at org.junit.jupiter.engine.execution.MethodInvocation.proceed(MethodInvocation.java:60)
	at org.junit.jupiter.engine.descriptor.ClassBasedTestDescriptor.invokeMethodInExtensionContext(ClassBasedTestDescriptor.java:520)
	at org.junit.jupiter.engine.descriptor.ClassBasedTestDescriptor.invokeBeforeEachMethods(ClassBasedTestDescriptor.java:504)
```

### CI log excerpt
```text
[r1007] 2026-09-23T15:00:27Z [ERROR] com.example.orders.inventory.InventoryClientTest.reservesStockForOrder -- Time elapsed: 0.012 s <<< ERROR!
[r1007] 2026-09-23T15:00:31Z [ERROR] com.example.orders.inventory.InventoryClientTest.releasesStockOnCancel -- Time elapsed: 0.012 s <<< ERROR!
[r1008] 2026-09-24T00:00:27Z [ERROR] com.example.orders.inventory.InventoryClientTest.reservesStockForOrder -- Time elapsed: 0.012 s <<< ERROR!
[r1008] 2026-09-24T00:00:31Z [ERROR] com.example.orders.inventory.InventoryClientTest.releasesStockOnCancel -- Time elapsed: 0.012 s <<< ERROR!
[r1009] 2026-09-24T09:00:27Z [ERROR] com.example.orders.inventory.InventoryClientTest.reservesStockForOrder -- Time elapsed: 0.012 s <<< ERROR!
[r1009] 2026-09-24T09:00:31Z [ERROR] com.example.orders.inventory.InventoryClientTest.releasesStockOnCancel -- Time elapsed: 0.012 s <<< ERROR!
```

<!-- triage-signature: a8252e02cf -->
