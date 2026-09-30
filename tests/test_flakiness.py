import pytest

from ci_triage.flakiness import history_for, is_flaky, trailing_failure_streak
from ci_triage.models import Outcome, RunOutcome

P, F = Outcome.PASSED, Outcome.FAILED


def _history(*pairs):
    outcomes = [RunOutcome(run_id=f"r{i}", commit=sha, outcome=o) for i, (sha, o) in enumerate(pairs)]
    return history_for("t", outcomes)


def test_same_commit_flip_rate():
    h = _history(("a", P), ("a", F), ("b", P), ("b", P), ("c", F), ("c", P), ("d", P))
    assert h.commits_with_reruns == 3
    assert h.flipped_commits == ["a", "c"]
    assert h.same_commit_flip_rate == pytest.approx(0.667)
    assert h.is_flaky
    assert h.fail_rate == pytest.approx(2 / 7, abs=1e-3)


def test_regression_reports_first_failing_and_last_passing_commit():
    h = _history(("a", P), ("b", P), ("c", F), ("c", F), ("d", F))
    assert not h.is_flaky
    assert h.failing_since_commit == "c"
    assert h.last_passing_commit == "b"
    assert h.failing_streak == 3
    assert h.transitions == 1


def test_always_failing_has_no_last_passing_commit():
    h = _history(("a", F), ("b", F))
    assert h.failing_since_commit == "a"
    assert h.last_passing_commit is None


def test_single_failure_then_recovery_is_not_flaky():
    h = _history(("a", P), ("b", F), ("c", P))
    assert not h.is_flaky
    assert h.failing_since_commit is None
    assert h.transitions == 2


def test_toggling_across_commits_without_reruns_is_flaky():
    h = _history(("a", F), ("b", P), ("c", F), ("d", P))
    assert h.commits_with_reruns == 0
    assert h.is_flaky


def test_error_counts_as_failure():
    h = _history(("a", P), ("b", Outcome.ERROR))
    assert h.failures == 1 and h.failing_since_commit == "b"


@pytest.mark.parametrize(
    ("failed", "streak"), [([], 0), ([True], 1), ([True, False], 0), ([False, True, True], 2)]
)
def test_trailing_failure_streak(failed, streak):
    assert trailing_failure_streak(failed) == streak


def test_is_flaky_rules():
    assert is_flaky(["a"], 1, 1)
    assert not is_flaky([], 1, 2)
    assert is_flaky([], 2, 3)


def test_sample_data_histories(histories):
    flaky = histories["tests.api.test_checkout::test_checkout_completes_within_sla"]
    assert flaky.is_flaky and flaky.flipped_commits == ["3f2a9c1", "e7a1b52"]
    regression = histories["com.example.orders.pricing.OrderPricingTest::appliesBulkDiscountAboveThreshold"]
    assert not regression.is_flaky and regression.failing_since_commit == "9c41e7a"
    env = histories["tests.api.test_user_profile::test_get_profile"]
    assert not env.is_flaky and env.failures == 1
