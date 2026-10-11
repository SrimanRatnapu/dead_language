import importlib.util
import json
import sys
from pathlib import Path

import pytest

from deadlang import config, llm
from deadlang.llm import BudgetExceeded
from deadlang.schemas import SpecialistReply
from deadlang.specialists.price import PriceChecker
from tests.fakes import make_listing

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compute_triage.py"
spec = importlib.util.spec_from_file_location("compute_triage", SCRIPT)
triage = importlib.util.module_from_spec(spec)
sys.modules["compute_triage"] = triage     # dataclasses look the module up here
spec.loader.exec_module(triage)


class Market:
    def __init__(self, listings):
        self.listings = {l.id: l for l in listings}

    async def all_active(self):
        return [l for l in self.listings.values() if l.status == "active"]

    async def get_listing_snapshot(self, listing_id):
        return self.listings[listing_id]


class FakeRatio:
    """Stands in for PriceChecker: ratio per listing id (None = no comparables)."""

    def __init__(self, ratios=None):
        self.ratios = ratios or {}

    async def run(self, call):
        from deadlang.schemas import EvidenceDraft
        ratio = self.ratios.get(call.listing_id)
        return SpecialistReply(ok=True, drafts=[EvidenceDraft(
            capability="price_check", summary="x", data={"ratio": ratio}, produced_by="code",
            specialist_name="deadlang-price-checker")])


class FakeJson:
    def __init__(self, suspicion=0.6, reason="Price is far above bone.", fail_after=None, error=None):
        self.suspicion, self.reason = suspicion, reason
        self.fail_after, self.error = fail_after, error
        self.calls = []

    async def __call__(self, **kw):
        self.calls.append(kw)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise self.error
        return {"text_suspicion": self.suspicion, "reason": self.reason}


def listings(n):
    return [make_listing(id=f"L{i:04d}", title=f"Netsuke {i}") for i in range(n)]


@pytest.fixture(autouse=True)
def _tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")


# ---------------- scoring ----------------

@pytest.mark.parametrize("suspicion,ratio,score", [(0.8, 20, 0.9), (0.0, 0, 0.0), (0.4, 5.0, 0.45),
                                                   (1.0, 3.0, 0.65), (0.33, 0, 0.17)])
def test_score_is_half_text_suspicion_and_half_capped_price_ratio(suspicion, ratio, score):
    assert triage.combine(suspicion, ratio) == score


def test_listing_text_has_only_the_allowed_fields():
    text = triage.listing_text(make_listing(title="Old netsuke", description="From my grandfather",
                                            price_usd=1450.0, stated_material="bone", item_type="netsuke",
                                            ship_from="HK", image_paths=["images/L0101_0.jpg"]))
    for part in ("Old netsuke", "From my grandfather", "$1,450", "bone", "netsuke"):
        assert part in text
    for part in ("HK", "images/", "S0042"):
        assert part not in text


async def test_score_listing_combines_the_model_read_with_the_price_ratio(monkeypatch):
    fake = FakeJson(suspicion=0.6, reason="Price is far above bone.")
    monkeypatch.setattr(llm, "call_json", fake)
    row = await triage.score_listing(make_listing(id="L1"), FakeRatio({"L1": 12.3}), "triage-0")
    assert row == {"score": 0.8, "reason": "Price is far above bone.", "price_ratio": 12.3}
    call = fake.calls[0]
    assert call["model"] == config.MODEL_FAST and call["case_id"] == "triage-0"
    assert call["schema_name"] == "report_triage" and "image_paths" not in call
    assert "most listings are innocent" in call["system"].lower()


async def test_no_comparables_means_price_ratio_zero(monkeypatch):
    monkeypatch.setattr(llm, "call_json", FakeJson(suspicion=0.4))
    row = await triage.score_listing(make_listing(id="L1"), FakeRatio({"L1": None}), "triage-0")
    assert (row["price_ratio"], row["score"]) == (0.0, 0.2)


async def test_works_with_the_real_price_checker(monkeypatch):
    monkeypatch.setattr(llm, "call_json", FakeJson(suspicion=1.0))
    market = Market([make_listing(id="L1")])
    row = await triage.score_listing(make_listing(id="L1"), PriceChecker(market), "triage-0")
    assert row["price_ratio"] == 0.0 and row["score"] == 0.5     # one listing: nothing to compare with


async def test_model_numbers_are_clamped(monkeypatch):
    monkeypatch.setattr(llm, "call_json", FakeJson(suspicion=7, reason="  spaced  "))
    row = await triage.score_listing(make_listing(id="L1"), FakeRatio(), "triage-0")
    assert row["score"] == 0.5 and row["reason"] == "spaced"


# ---------------- the run ----------------

async def test_compute_scores_every_listing_and_shards_case_ids(monkeypatch):
    fake = FakeJson()
    monkeypatch.setattr(llm, "call_json", fake)
    monkeypatch.setattr(triage, "SHARD", 2)
    result = await triage.compute(listings(5), FakeRatio(), concurrency=1, run_id="t1")
    assert sorted(result.scores) == [f"L{i:04d}" for i in range(5)]
    assert [c["case_id"] for c in fake.calls] == ["triage-t1-0", "triage-t1-0", "triage-t1-1", "triage-t1-1", "triage-t1-2"]
    assert result.stopped is None and result.failed == 0


async def test_budget_exceeded_keeps_what_was_scored_and_stops(monkeypatch):
    fake = FakeJson(fail_after=2, error=BudgetExceeded("triage cap"))
    monkeypatch.setattr(llm, "call_json", fake)
    result = await triage.compute(listings(6), FakeRatio(), concurrency=1)
    assert len(result.scores) == 2 and result.stopped == "budget"
    assert len(fake.calls) == 3                 # nothing is called after the cap is hit


async def test_one_failed_listing_is_skipped_not_fatal(monkeypatch):
    class Flaky(FakeJson):
        async def __call__(self, **kw):
            self.calls.append(kw)
            if "Netsuke 1\n" in kw["user"]:
                raise ValueError("no tool output")
            return {"text_suspicion": 0.1, "reason": "ok"}

    monkeypatch.setattr(llm, "call_json", Flaky())
    result = await triage.compute(listings(3), FakeRatio(), concurrency=1)
    assert sorted(result.scores) == ["L0000", "L0002"] and result.failed == 1 and result.stopped is None


async def test_gives_up_when_every_call_fails(monkeypatch):
    fake = FakeJson(fail_after=0, error=RuntimeError("401 bad key"))
    monkeypatch.setattr(llm, "call_json", fake)
    result = await triage.compute(listings(20), FakeRatio(), concurrency=1)
    assert result.scores == {} and result.stopped == "errors" and len(fake.calls) == triage.GIVE_UP_AFTER
    assert "401 bad key" in result.last_error


# ---------------- command line ----------------

def run_main(monkeypatch, argv, market, ask=lambda p: "y", fake=None):
    fake = fake or FakeJson()
    monkeypatch.setattr(llm, "call_json", fake)
    import asyncio
    code = asyncio.run(triage.main(argv, market=market, price_checker=FakeRatio({"L0000": 25.0}), ask=ask))
    return code, fake


def test_declining_the_confirmation_makes_no_calls_and_writes_nothing(monkeypatch, tmp_path, capsys):
    code, fake = run_main(monkeypatch, [], Market(listings(3)), ask=lambda p: "n")
    assert code == 1 and fake.calls == [] and not (tmp_path / "triage.json").exists()
    out = capsys.readouterr().out
    assert "3 real API calls" in out and "Estimated" in out and "No calls were made" in out


def test_accepting_writes_triage_json_the_api_can_read(monkeypatch, tmp_path):
    code, fake = run_main(monkeypatch, [], Market(listings(3)))
    assert code == 0 and len(fake.calls) == 3
    data = json.loads((tmp_path / "triage.json").read_text())
    assert set(data) == {"L0000", "L0001", "L0002"}
    assert data["L0000"] == {"score": 0.8, "reason": "Price is far above bone.", "price_ratio": 25.0}
    assert all({"score", "reason"} <= set(v) for v in data.values())


def test_dry_run_prints_the_estimate_and_stops(monkeypatch, tmp_path, capsys):
    def never(prompt):
        raise AssertionError("dry run must not ask")

    code, fake = run_main(monkeypatch, ["--dry-run"], Market(listings(3)), ask=never)
    assert code == 0 and fake.calls == [] and not (tmp_path / "triage.json").exists()
    assert "Estimated" in capsys.readouterr().out


def test_yes_flag_skips_the_question(monkeypatch):
    def never(prompt):
        raise AssertionError("--yes must not ask")

    code, fake = run_main(monkeypatch, ["--yes"], Market(listings(2)), ask=never)
    assert code == 0 and len(fake.calls) == 2


def test_limit_and_resume_only_score_what_is_missing(monkeypatch, tmp_path):
    (tmp_path / "triage.json").write_text(json.dumps({"L0000": {"score": 0.1, "reason": "old", "price_ratio": 0}}))
    code, fake = run_main(monkeypatch, ["--yes", "--limit", "2"], Market(listings(5)))
    data = json.loads((tmp_path / "triage.json").read_text())
    assert code == 0 and len(fake.calls) == 2
    assert data["L0000"]["reason"] == "old"                      # kept, not re-scored
    assert sorted(data) == ["L0000", "L0001", "L0002"]


def test_force_rescoring_replaces_existing_rows(monkeypatch, tmp_path):
    (tmp_path / "triage.json").write_text(json.dumps({"L0000": {"score": 0.1, "reason": "old", "price_ratio": 0}}))
    code, fake = run_main(monkeypatch, ["--yes", "--force"], Market(listings(1)))
    assert len(fake.calls) == 1
    assert json.loads((tmp_path / "triage.json").read_text())["L0000"]["reason"] == "Price is far above bone."


def test_budget_stop_saves_partial_results_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    fake = FakeJson(fail_after=1, error=BudgetExceeded("cap"))
    code, _ = run_main(monkeypatch, ["--yes", "--concurrency", "1"], Market(listings(4)), fake=fake)
    assert code == 2
    assert list(json.loads((tmp_path / "triage.json").read_text())) == ["L0000"]
    assert "budget" in capsys.readouterr().out.lower()


def test_nothing_to_do_makes_no_calls(monkeypatch, tmp_path, capsys):
    (tmp_path / "triage.json").write_text(json.dumps({"L0000": {"score": 0.1, "reason": "x", "price_ratio": 0}}))
    code, fake = run_main(monkeypatch, [], Market(listings(1)), ask=lambda p: pytest.fail("asked"))
    assert code == 0 and fake.calls == [] and "Nothing to score" in capsys.readouterr().out


def test_missing_marketplace_data_is_a_clear_message_not_a_traceback(monkeypatch, capsys):
    class NoData(Market):
        async def all_active(self):
            raise FileNotFoundError(2, "No such file", "data/listings.jsonl")

    code, fake = run_main(monkeypatch, [], NoData([]))
    out = capsys.readouterr().out
    assert code == 2 and fake.calls == []
    assert "data/listings.jsonl" in out and "build" in out.lower()


async def test_each_triage_run_uses_fresh_case_ids(monkeypatch):
    fake = FakeJson()
    monkeypatch.setattr(llm, "call_json", fake)
    await triage.compute(listings(2), FakeRatio(), concurrency=1)
    await triage.compute(listings(2), FakeRatio(), concurrency=1)
    assert len({c["case_id"] for c in fake.calls}) == 2                  # a rerun does not inherit the last run's usage


async def test_a_triage_budget_stop_keeps_the_reason(monkeypatch):
    fake = FakeJson(fail_after=1, error=BudgetExceeded("case triage-x-0 output cap 30,000: used 29,900 + 0 in flight + 200 for this call"))
    monkeypatch.setattr(llm, "call_json", fake)
    result = await triage.compute(listings(4), FakeRatio(), concurrency=1)
    assert result.stopped == "budget" and "output cap 30,000" in result.last_error


def test_the_triage_plan_has_per_case_numbers():
    b = triage.plan(listings(3), concurrency=4)[0]
    assert b.calls_per_case == triage.SHARD and b.concurrency == 4
