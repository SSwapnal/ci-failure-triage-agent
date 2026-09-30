from types import SimpleNamespace

import anthropic
import httpx
import pytest

from ci_triage.llm import AnthropicClassifier, MockClassifier, build_user_prompt, get_classifier
from ci_triage.models import Classification

EXPECTED = {
    "appliesBulkDiscountAboveThreshold": ("product_bug", "9c41e7a"),
    "reservesStockForOrder": ("test_code_bug", "e7a1b52"),
    "test_checkout_completes_within_sla": ("flaky_test", None),
    "test_get_profile": ("environment", None),
    "quotesStandardShipping": ("environment", None),
    "test_export_csv_header_order": ("product_bug", "f3c9d18"),
}


@pytest.mark.parametrize(("test_name", "expected"), EXPECTED.items())
def test_mock_classifier_matches_planted_scenarios(by_test, test_name, expected):
    result = MockClassifier().classify(by_test[test_name])
    assert (result.category, result.suspected_commit) == expected
    assert Classification.model_validate(result.model_dump()) == result


def test_mock_is_unsure_about_single_observation(by_test):
    assert MockClassifier().classify(by_test["test_export_csv_header_order"]).confidence < 0.7
    assert MockClassifier().classify(by_test["appliesBulkDiscountAboveThreshold"]).confidence >= 0.7


def test_prompt_contains_evidence(by_test):
    prompt = build_user_prompt(by_test["appliesBulkDiscountAboveThreshold"])
    assert "9c41e7a" in prompt and "consistent_since_commit" in prompt


def test_confidence_is_clamped():
    c = Classification(category="environment", confidence=1.7, rationale="r", suggested_owner_area="ci")
    assert c.confidence == 1.0


def test_provider_selection(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(get_classifier(), MockClassifier)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(get_classifier(), AnthropicClassifier)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert isinstance(get_classifier(), MockClassifier)
    with pytest.raises(ValueError):
        get_classifier("openai")


def test_anthropic_provider_without_key_fails_fast(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        get_classifier("anthropic")


def test_model_override(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5-5")
    assert AnthropicClassifier(client=object()).model == "claude-opus-5-5"
    monkeypatch.delenv("LLM_MODEL")
    assert AnthropicClassifier(client=object()).model == "claude-sonnet-5-5"


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _classifier(**kw):
    messages = FakeMessages(**kw)
    return AnthropicClassifier(client=SimpleNamespace(messages=messages)), messages


def test_anthropic_classifier_returns_parsed_output(by_test):
    parsed = Classification(
        category="product_bug",
        confidence=0.9,
        rationale="r",
        suspected_commit="9c41e7a",
        suggested_owner_area="orders/pricing",
    )
    clf, messages = _classifier(response=SimpleNamespace(stop_reason="end_turn", parsed_output=parsed))
    assert clf.classify(by_test["appliesBulkDiscountAboveThreshold"]) == parsed
    call = messages.calls[0]
    assert call["output_format"] is Classification
    assert call["model"] == "claude-sonnet-5-5"


def test_anthropic_refusal_routes_to_review(by_test):
    clf, _ = _classifier(response=SimpleNamespace(stop_reason="refusal", parsed_output=None))
    assert clf.classify(by_test["appliesBulkDiscountAboveThreshold"]).confidence == 0.0


def test_anthropic_api_error_routes_to_review(by_test):
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    clf, _ = _classifier(error=error)
    result = clf.classify(by_test["appliesBulkDiscountAboveThreshold"])
    assert result.confidence == 0.0 and "APIConnectionError" in result.rationale
