import pytest

from deadlang import config, costs, llm
from deadlang.costs import Batch


def batch(**kw):
    base = dict(label="triage", model="claude-haiku-4-5-20251001", calls=100, input_tokens=1_000,
                output_tokens=100, max_output_tokens=200)
    return Batch(**{**base, **kw})


def test_price_uses_the_longest_matching_model_prefix():
    assert costs.price_for("claude-haiku-4-5-20251001") == (1.0, 5.0)
    assert costs.price_for("claude-sonnet-5-5") == (2.0, 10.0)
    assert costs.price_for("claude-sonnet-4-6") == (3.0, 15.0)
    assert costs.price_for("some-other-model") is None


def test_estimate_adds_up_tokens_and_dollars():
    est = costs.estimate([batch(), batch(label="exam", model="claude-sonnet-5-5", calls=10, input_tokens=2_000,
                                         output_tokens=50, max_output_tokens=1_500)])
    assert est.calls == 110
    assert est.input_tokens == 100 * 1_000 + 10 * 2_000
    assert est.output_tokens == 100 * 100 + 10 * 50
    assert est.worst_output_tokens == 100 * 200 + 10 * 1_500
    # haiku: 100k in * $1/M + 10k out * $5/M ; sonnet: 20k in * $2/M + 500 out * $10/M
    assert est.dollars == pytest.approx(0.1 + 0.05 + 0.04 + 0.005)
    assert est.worst_dollars == pytest.approx(0.1 + 0.1 + 0.04 + 0.15)


def test_unknown_model_price_means_no_dollar_figure():
    est = costs.estimate([batch(model="mystery-model")])
    assert est.dollars is None and est.worst_dollars is None
    assert "price unknown" in costs.report([batch(model="mystery-model")])


@pytest.fixture
def usage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 6_000_000)
    monkeypatch.setattr(config, "MAX_OUTPUT_TOKENS", 600_000)


def test_report_shows_calls_tokens_cost_and_budget_share(usage):
    text = costs.report([batch()])
    assert "100 real API calls" in text
    assert "100,000 in" in text and "10,000 out" in text
    assert "$0.15" in text            # 100k in at $1/M + 10k out at $5/M
    assert "worst case" in text
    assert "1.7%" in text             # 100,000 of 6,000,000 input tokens
    assert "WARNING" not in text


def test_report_warns_when_the_run_would_exceed_the_remaining_budget(usage, monkeypatch):
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 50_000)
    text = costs.report([batch()])
    assert "WARNING" in text and "input" in text


def test_report_counts_tokens_already_spent(usage, monkeypatch):
    usage_file = config.USAGE_FILE
    usage_file.write_text('{"global": {"input_tokens": 5950000, "output_tokens": 0, "calls": 9}, "cases": {}}')
    assert llm.usage_snapshot()["input_tokens"] == 5_950_000
    assert "WARNING" in costs.report([batch()])


def test_confirm_only_says_yes_to_yes(usage):
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return answer

    for answer, expected in [("y", True), ("YES", True), (" yes ", True), ("n", False), ("", False), ("sure", False)]:
        assert costs.confirm([batch()], ask=ask, out=lambda *_: None) is expected
    assert len(asked) == 6 and "100" in asked[0]


def test_confirm_with_assume_yes_does_not_ask(usage):
    def ask(prompt):
        raise AssertionError("must not ask")

    assert costs.confirm([batch()], assume_yes=True, ask=ask, out=lambda *_: None) is True


def test_confirm_without_a_terminal_is_a_no(usage):
    def ask(prompt):
        raise EOFError

    assert costs.confirm([batch()], ask=ask, out=lambda *_: None) is False


def test_confirm_prints_the_report_before_asking(usage):
    printed = []
    costs.confirm([batch()], ask=lambda p: "n", out=printed.append)
    assert any("real API calls" in str(p) for p in printed)
