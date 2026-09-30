from pathlib import Path

import pytest

from ci_triage.clustering import cluster_failures
from ci_triage.flakiness import analyze_history
from ci_triage.ingest import load_runs

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return SAMPLE_DIR


@pytest.fixture(scope="session")
def runs():
    return load_runs(SAMPLE_DIR)


@pytest.fixture(scope="session")
def histories(runs):
    return analyze_history(runs)


@pytest.fixture(scope="session")
def clusters(runs, histories):
    return cluster_failures(runs, histories)


@pytest.fixture(scope="session")
def by_test(clusters):
    """Cluster lookup by any member test name."""
    return {t.split("::")[1]: c for c in clusters for t in c.tests}
