"""Cluster classification: Anthropic Claude with structured output, or a deterministic mock.

Provider selection (env):
    LLM_PROVIDER   anthropic | mock   (default: anthropic if ANTHROPIC_API_KEY is set, else mock)
    LLM_MODEL      model id           (default: claude-sonnet-5-5)
    ANTHROPIC_API_KEY
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from ci_triage.models import Classification, ClusterEvidence

DEFAULT_MODEL = "claude-sonnet-5-5"

SYSTEM_PROMPT = """\
You are a senior QA engineer triaging CI test failures. You receive one failure
group at a time: failures that share an exception type, normalized message and
top in-app stack frame, plus deterministic evidence computed from CI history.

Classify the group into exactly one category:
- product_bug: the code under test is wrong. Typical evidence: consistent failure
  starting at a specific commit, assertion on business values, no infra signals.
- flaky_test: the test is non-deterministic. Typical evidence: outcome changed
  between reruns of the same commit, timing/ordering/async assertions.
- environment: CI infrastructure or dependencies failed (network, DNS, containers,
  databases, disk, OOM). Typical evidence: infra signals, many unrelated tests
  failing in the same run, recovery on the next run without a code change.
- test_code_bug: the test itself is broken (setup/fixture errors, NPE or
  AttributeError inside test code, wrong test data) after a test change.

Rules:
- Treat the deterministic evidence as ground truth; do not contradict it.
- Confidence reflects how well the evidence supports the category. Use < 0.7
  when history is too short (e.g. a single observation) or signals conflict.
- suspected_commit must be one of the listed suspect commits, or null.
- suggested_owner_area: a code area from the evidence (e.g. "orders/pricing"),
  or "ci-infrastructure" for environment problems.
- The rationale must cite concrete evidence (runs, commits, flip rate, signals).
"""


class Classifier(Protocol):
    name: str

    def classify(self, evidence: ClusterEvidence) -> Classification: ...


def build_user_prompt(evidence: ClusterEvidence) -> str:
    payload = evidence.model_dump(mode="json")
    return f"Classify this CI failure group.\n\n<evidence>\n{json.dumps(payload, indent=2)}\n</evidence>"


class AnthropicClassifier:
    """Calls Claude with the evidence and parses the reply into :class:`Classification`."""

    def __init__(self, model: str | None = None, client=None) -> None:
        import anthropic

        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.name = f"anthropic:{self.model}"
        self._anthropic = anthropic
        self._client = client or anthropic.Anthropic()

    def classify(self, evidence: ClusterEvidence) -> Classification:
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(evidence)}],
                output_format=Classification,
            )
        except (self._anthropic.APIStatusError, self._anthropic.APIConnectionError) as exc:
            return _unclassified(evidence, f"LLM call failed ({type(exc).__name__}): {exc}")

        if response.stop_reason == "refusal":
            return _unclassified(evidence, "The model declined to classify this group.")
        if response.parsed_output is None:
            return _unclassified(evidence, f"No structured output (stop_reason={response.stop_reason}).")
        return response.parsed_output


class MockClassifier:
    """Deterministic stand-in for the LLM, used for demos, tests and CI.

    It applies the same decision guidance as the system prompt to the evidence,
    so its output is schema-valid and consistent with the sample data. It is a
    reasonable baseline, not a replacement for the model on messy real data.
    """

    name = "mock"

    def classify(self, e: ClusterEvidence) -> Classification:
        test_area = e.code_areas[0] if e.code_areas else "unknown"
        suspect = e.suspect_commits[-1].sha if e.suspect_commits else None

        if e.infra_signals and (e.single_run_burst or not e.consistent_since_commit):
            runs = ", ".join(e.failing_runs)
            return Classification(
                category="environment",
                confidence=0.9 if e.single_run_burst else 0.75,
                rationale=(
                    f"{len(e.tests)} test(s) failed only in {runs} with infra signals "
                    f"({', '.join(e.infra_signals)}). "
                    + (
                        "The tests pass again in later runs without a code change, "
                        if not e.failing_in_latest_run
                        else ""
                    )
                    + "which points at CI infrastructure rather than the product."
                ),
                suspected_commit=None,
                suggested_owner_area="ci-infrastructure",
            )

        if e.any_test_flaky:
            return Classification(
                category="flaky_test",
                confidence=round(min(0.9, 0.6 + 0.3 * e.max_same_commit_flip_rate), 2),
                rationale=(
                    f"Failed in {len(e.failing_runs)}/{e.total_runs} runs and changed outcome between "
                    f"reruns of the same commit (flip rate {e.max_same_commit_flip_rate:.2f}). "
                    f"Failure message: {e.normalized_message!r}. A test that changes outcome without a "
                    "code change should be stabilised or quarantined, not filed as a product bug."
                ),
                suspected_commit=None,
                suggested_owner_area=test_area,
            )

        if e.consistent_since_commit and (
            e.setup_phase or (e.failure_kind == "error" and e.frames_in_test_code)
        ):
            return Classification(
                category="test_code_bug",
                confidence=0.85 if e.failing_streak >= 2 else 0.6,
                rationale=(
                    f"{e.exc_type} raised in test code ({', '.join(e.top_frames)}) during setup, "
                    f"failing every run since {e.consistent_since_commit} "
                    f"({_commit_msg(e)!r}). The error is in the test harness before the product "
                    "code is exercised, so this is a test-code problem."
                ),
                suspected_commit=suspect,
                suggested_owner_area=test_area,
            )

        if e.consistent_since_commit:
            if e.failing_streak >= 2:
                return Classification(
                    category="product_bug",
                    confidence=0.85,
                    rationale=(
                        f"Passed through {e.last_passing_commit} and failed in all {e.failing_streak} runs "
                        f"since {e.consistent_since_commit}, with no same-commit flips and no infra signals. "
                        f"The assertion on a business value ({e.sample_message[:80]!r}) points at "
                        f"{e.consistent_since_commit} ({_commit_msg(e)!r})."
                    ),
                    suspected_commit=suspect,
                    suggested_owner_area=test_area,
                )
            return Classification(
                category="product_bug",
                confidence=0.55,
                rationale=(
                    f"New failure seen only once, in the latest run on {e.consistent_since_commit} "
                    f"({_commit_msg(e)!r}). A single observation cannot distinguish a regression "
                    "from a flaky failure; rerun to confirm before filing."
                ),
                suspected_commit=suspect,
                suggested_owner_area=test_area,
            )

        return Classification(
            category="product_bug",
            confidence=0.4,
            rationale="Intermittent failure without a clear flip pattern or infra signal; needs a human look.",
            suspected_commit=None,
            suggested_owner_area=test_area,
        )


def _commit_msg(e: ClusterEvidence) -> str:
    return e.suspect_commits[-1].message if e.suspect_commits else ""


def _unclassified(evidence: ClusterEvidence, reason: str) -> Classification:
    """Zero-confidence placeholder so the group is routed to human review."""
    return Classification(
        category="product_bug",
        confidence=0.0,
        rationale=reason,
        suspected_commit=None,
        suggested_owner_area=evidence.code_areas[0] if evidence.code_areas else "unknown",
    )


def get_classifier(provider: str | None = None, model: str | None = None) -> Classifier:
    provider = (
        provider
        or os.environ.get("LLM_PROVIDER")
        or ("anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock")
    )
    if provider == "mock":
        return MockClassifier()
    if provider == "anthropic":
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise ValueError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY (or use LLM_PROVIDER=mock)")
        return AnthropicClassifier(model=model)
    raise ValueError(f"unknown LLM provider: {provider!r} (expected 'anthropic' or 'mock')")
