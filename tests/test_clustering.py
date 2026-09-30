def test_sample_data_groups_into_six_signatures(clusters):
    assert len(clusters) == 6
    assert sum(c.occurrences for c in clusters) == 21


def test_regression_cluster_evidence(by_test):
    c = by_test["appliesBulkDiscountAboveThreshold"]
    assert c.consistent_since_commit == "9c41e7a"
    assert c.last_passing_commit == "7b8e4d0"
    assert [s.sha for s in c.suspect_commits] == ["9c41e7a"]
    assert c.failing_streak == 6
    assert not c.infra_signals and not c.any_test_flaky


def test_environment_clusters_pick_up_job_log_signals(by_test):
    db = by_test["test_get_profile"]
    assert db.single_run_burst and db.failing_runs == ["r1006"]
    assert {"connection refused", "container OOM-killed"} <= set(db.infra_signals)
    assert any("OOMKilled" in line for line in db.log_excerpt)
    dns = by_test["quotesStandardShipping"]
    assert dns is by_test["quotesExpressShipping"]
    assert "dns resolution failure" in dns.infra_signals


def test_setup_npe_cluster(by_test):
    c = by_test["reservesStockForOrder"]
    assert c is by_test["releasesStockOnCancel"]
    assert c.setup_phase and c.frames_in_test_code and c.failure_kind == "error"
    assert c.consistent_since_commit == "e7a1b52"


def test_flaky_cluster_includes_preceding_warning(by_test):
    c = by_test["test_checkout_completes_within_sla"]
    assert c.any_test_flaky and c.max_same_commit_flip_rate > 0.5
    assert c.consistent_since_commit is None
    assert any("slow upstream" in line for line in c.log_excerpt)


def test_new_failure_in_latest_run(by_test):
    c = by_test["test_export_csv_header_order"]
    assert c.failing_in_latest_run and c.failing_streak == 1
