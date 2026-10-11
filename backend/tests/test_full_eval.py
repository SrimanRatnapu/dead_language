"""Full-set end-to-end evaluation (v2 B2). Stub agents and a stub model client only: no API calls."""
import asyncio
import json
from collections import Counter
from types import SimpleNamespace as NS

import pytest

from deadlang import config, llm
from deadlang.agntcy.cards import ALL_AGENT_NAMES, card_for
from deadlang.agntcy.discovery import LocalDiscovery
from deadlang.agntcy.transport import LocalTransport
from deadlang.deliberation import crosscase
from deadlang.deliberation.facilitator import AGENTS
from deadlang.eval import full_eval as fe
from deadlang.llm import BudgetExceeded
from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import Claim, StancePost
from deadlang.specialists.network import LinkedSellers, SellerInventory
from deadlang.specialists.price import PriceChecker
from tests.conftest import make_listing, make_seller
from tests.fakes import FakeTriage

OFFICER = crosscase.CROSS_CASE_ROLE
UNDERCOVER, COUNSEL = [a for a in AGENTS if a != OFFICER]


# ---------------------------------------------------------------- a tiny labelled marketplace

CATS = {"ivory": True, "legal_bone": False, "legal_resin": False, "tagua": False, "other_legal": False}


def write_data(tmp_path, per_cat=None, languages=None, ships=None):
    """data/listings.jsonl + labels.csv with listings per category; returns the item ids by category."""
    per_cat = per_cat or {"ivory": 3, "legal_bone": 4, "legal_resin": 4, "tagua": 2, "other_legal": 3}
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    listings, labels, ids = [], ["listing_id,truth,should_flag,notes"], {}
    n = 0
    for cat, count in per_cat.items():
        for _ in range(count):
            n += 1
            lid = f"L{n:04d}"
            lang = (languages or {}).get(lid, "en")
            ship = (ships or {}).get(lid, "US-CA")
            listings.append(make_listing(lid, f"S{n}", f"Item {n}", f"Description {n}", 100.0, language=lang, ship_from=ship))
            labels.append(f"{lid},{cat},{str(CATS[cat]).lower()},")
            ids.setdefault(cat, []).append(lid)
    (data / "listings.jsonl").write_text("".join(l.model_dump_json() + "\n" for l in listings), encoding="utf-8")
    (data / "labels.csv").write_text("\n".join(labels) + "\n", encoding="utf-8")
    return data, listings, ids


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")
    data, listings, ids = write_data(tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", data)
    market = LocalMarketplaceClient(MarketplaceStore(listings, [make_seller(f"S{i}") for i in range(1, len(listings) + 1)]), data)
    return SimpleWorld(tmp_path, data, listings, ids, market)


class SimpleWorld:
    def __init__(self, tmp, data, listings, ids, market):
        self.tmp, self.data, self.listings, self.ids, self.market = tmp, data, listings, ids, market


class StubAgent:
    def __init__(self, name, stance="file", fail=False, budget=False):
        self.name, self.stance, self.fail, self.budget, self.turns = name, stance, fail, budget, []

    async def handle(self, turn):
        self.turns.append(turn)
        if self.budget:
            raise BudgetExceeded("case cap")
        if self.fail:
            raise RuntimeError("Error code: 401 - invalid x-api-key")
        return StancePost(agent=self.name, round=turn.round, stance=self.stance, confidence=0.7,
                          claims=[Claim(text="The listing describes the item as bone.", evidence_ids=["E0"]),
                                  Claim(text="Priced at $9,999.", evidence_ids=["E0"])],      # the second is not grounded: rejected
                          take="x")


def evaluator(world, run_id="r1", stances=("file", "file", "file"), triage_scores=None, fail=(), budget=(), screen=None):
    agents = {role: StubAgent(role, stance, fail=role in fail, budget=role in budget)
              for role, stance in zip(AGENTS, stances)}
    specs = [SellerInventory(world.market), LinkedSellers(world.market), PriceChecker(world.market)]
    discovery = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
    transport = LocalTransport({s.name: s for s in specs}, agents, discovery=discovery)
    fake = FakeTriage(scores=triage_scores or {}, default=0.9)

    async def model_flag(listing, seller=None, **kw):             # the real one, asked for the raw flag, flags what the model finds suspicious
        return await fake.screen(listing, seller, **{**kw, "threshold": 0.5})

    ev = fe.Evaluator(run_id, world.market, transport, discovery, screen=screen or model_flag)
    ev.agents, ev.fake_triage = agents, fake
    return ev


def pop(world):
    return fe.load_population(world.data)


def item_by_id(world, lid):
    return next(i for i in pop(world) if i.id == lid)


# ---------------------------------------------------------------- population and order

def test_the_population_is_the_labelled_stored_listings_with_their_metadata(world):
    items = pop(world)
    assert len(items) == 16 and sum(i.label for i in items) == 3
    first = items[0]
    assert (first.id, first.label, first.category, first.language, first.country, first.material) == \
        ("L0001", True, "ivory", "en", "US", first.material)
    assert {i.country for i in items} == {"US"}


def test_listings_without_a_label_or_not_stored_are_left_out(world):
    labels = (world.data / "labels.csv").read_text().splitlines()
    (world.data / "labels.csv").write_text("\n".join(labels[:-2] + ["L9999,tagua,false,"]) + "\n")      # drop 2 labels, add an unstored id
    ids = {i.id for i in pop(world)}
    assert len(ids) == 14 and "L9999" not in ids


def test_only_the_stored_listings_file_is_read_never_live_or_new_listing_files(world):
    (world.data / "live_listings.jsonl").write_text(make_listing("L7777", "S1", "Live", "x").model_dump_json() + "\n")
    (world.data / "new_listings.jsonl").write_text(make_listing("L8888", "S1", "New", "x").model_dump_json() + "\n")
    assert {i.id for i in pop(world)}.isdisjoint({"L7777", "L8888"})


def test_all_positives_come_first_then_negatives_interleaved_across_categories(world):
    order = fe.order_population(pop(world), seed=1)
    labels = [i.label for i in order]
    assert labels == [True] * 3 + [False] * 13
    negatives = [i.category for i in order if not i.label]
    for k in range(1, len(negatives) + 1):                     # stop anywhere: no category is ahead of another by more than 1
        counts = Counter(negatives[:k])
        spread = max(counts.get(c, 0) for c in ("legal_bone", "legal_resin", "tagua", "other_legal")) - \
            min(counts.get(c, 0) for c in ("legal_bone", "legal_resin", "tagua", "other_legal"))
        if k <= 8:                                              # until the smallest category (tagua: 2) runs out
            assert spread <= 1, (k, counts)


def test_the_order_is_seeded_and_deterministic(world):
    a = [i.id for i in fe.order_population(pop(world), seed=7)]
    assert a == [i.id for i in fe.order_population(pop(world), seed=7)]
    assert a != [i.id for i in fe.order_population(pop(world), seed=8)]
    assert sorted(a) == sorted(i.id for i in pop(world))        # nothing lost or repeated


def test_limit_takes_the_first_n_of_the_balanced_order(world):
    selected = fe.select(pop(world), limit=5, seed=0)
    assert [i.id for i in selected] == [i.id for i in fe.order_population(pop(world), seed=0)][:5]
    assert sum(i.label for i in selected) == 3


def test_stratified_keeps_all_positives_and_a_proportional_share_of_each_negative_category(world):
    selected = fe.select(pop(world), stratified=9, seed=0)
    assert len(selected) == 9 and sum(i.label for i in selected) == 3 and [i.label for i in selected][:3] == [True] * 3
    negatives = Counter(i.category for i in selected if not i.label)
    assert sum(negatives.values()) == 6 and all(v >= 1 for v in negatives.values())     # every category is represented
    assert negatives["legal_bone"] >= negatives["tagua"]                                 # bigger categories get more


def test_stratified_smaller_than_the_positives_takes_positives_only_and_larger_than_everything_takes_all(world):
    assert [i.label for i in fe.select(pop(world), stratified=2, seed=0)] == [True, True]
    assert len(fe.select(pop(world), stratified=500, seed=0)) == 16


# ---------------------------------------------------------------- one listing

async def test_a_row_has_everything_the_scoring_needs(world):
    ev = evaluator(world, stances=("file", "dismiss", "need_more"), triage_scores={"L0001": 0.8})
    row = await ev.run_listing(item_by_id(world, "L0001"))
    assert row["errors"] == [] and row["listing_id"] == "L0001" and row["run_id"] == "r1"
    assert (row["label"], row["category"], row["language"], row["country"]) == (True, "ivory", "en", "US")
    assert row["triage"]["score"] == 0.8 and row["triage"]["flagged"] is True
    assert row["outcome"] in ("CONTESTED", "WATCHLIST", "FILE", "DISMISS") and row["rounds"] >= 1
    assert OFFICER in row["sat_out"] and row["case_officer_abstained"] is True        # this listing has nothing to compare
    assert OFFICER not in row["agents_ran"] and UNDERCOVER in row["agents_ran"] and COUNSEL in row["agents_ran"]
    claims = row["claims"][UNDERCOVER]
    assert claims["made"] >= 2 and claims["rejected"] >= 1                              # the ungrounded $9,999 claim was rejected
    assert set(row["tokens"]) == {"triage", "agents"} and set(row["cost_usd"]) == {"triage", "agents", "total"}
    assert set(row["duration_s"]) == {"triage", "agents", "total"}
    assert row["stop_reason"]


async def test_the_label_never_reaches_a_model(world):
    seen = []

    async def spy(listing, seller=None, **kw):
        seen.append((listing, seller, kw))
        return await FakeTriage(default=0.9).screen(listing, seller, **kw)

    ev = evaluator(world, screen=spy)
    await ev.run_listing(item_by_id(world, "L0001"))
    assert len(seen) == 1 and set(seen[0][2]) <= {"price_ratio", "seller_listing_count", "case_id", "threshold"}
    for agent in ev.agents.values():
        for turn in agent.turns:
            assert "ivory" not in turn.model_dump_json().lower().replace("elephant ivory", "")


async def test_triage_runs_on_every_listing_whatever_it_says_and_asks_for_the_models_raw_flag(world):
    ev = evaluator(world, triage_scores={"L0006": 0.01})                                # triage would clear this listing
    row = await ev.run_listing(item_by_id(world, "L0006"))
    assert row["triage"]["score"] == 0.01 and row["triage"]["flagged"] is False
    assert ev.agents[UNDERCOVER].turns, "the agents run even when triage clears the listing"
    assert row["agents_ran"]


async def test_ids_are_fresh_per_run_and_one_case_per_listing(world):
    seen = []

    async def spy(listing, seller=None, **kw):
        seen.append(kw["case_id"])
        return await FakeTriage(default=0.5).screen(listing, seller, **kw)

    await evaluator(world, run_id="runA", screen=spy).run_listing(item_by_id(world, "L0001"))
    await evaluator(world, run_id="runB", screen=spy).run_listing(item_by_id(world, "L0001"))
    assert seen == ["ev-runA-L0001-t", "ev-runB-L0001-t"]


async def test_an_agent_that_fails_is_an_error_not_a_stance(world):
    ev = evaluator(world, fail=(COUNSEL,))
    row = await ev.run_listing(item_by_id(world, "L0001"))
    assert row["errors"] and any("401" in e or "invalid" in e for e in row["errors"])
    assert row["errors"][0].startswith("agent")


async def test_a_triage_that_could_not_run_is_an_error(world):
    from deadlang import triage

    async def broken(listing, seller=None, **kw):
        from deadlang.schemas import TriageResult
        return TriageResult(score=0.5, suspicious=True, reason=f"{triage.COULD_NOT_RUN} (RuntimeError), so this listing goes to the agents.")

    row = await evaluator(world, screen=broken).run_listing(item_by_id(world, "L0001"))
    assert row["errors"] and row["errors"][0].startswith("triage")


async def test_a_spent_budget_is_recorded_and_marks_the_row_so_the_run_can_stop(world):
    row = await evaluator(world, budget=(UNDERCOVER,)).run_listing(item_by_id(world, "L0001"))
    assert row["errors"] and row["budget_stop"] is True


async def test_an_exception_in_triage_is_recorded_as_an_error(world):
    async def explode(listing, seller=None, **kw):
        raise BudgetExceeded("global input cap reached")

    row = await evaluator(world, screen=explode).run_listing(item_by_id(world, "L0001"))
    assert row["budget_stop"] is True and row["errors"]


@pytest.mark.parametrize("text,kind", [
    ("Error code: 401 - invalid x-api-key", "error"), ("Your credit balance is too low", "error"),
    ("rate_limit_error: 429", "error"), ("Overloaded", "error"), ("budget", "budget"),
    ("no_images", "warning"), ("listing_removed", "warning"), ("cannot connect: deadlang-legal-table is not running", "warning")])
def test_specialist_errors_are_sorted_into_errors_budget_and_harmless_warnings(text, kind):
    assert fe.classify_specialist_error(text) == kind


# ---------------------------------------------------------------- tokens and cost, through the real llm accounting

class Scripted:
    """A stub Anthropic client: answers by tool name, reports usage with cache tokens."""

    def __init__(self):
        self.messages = self

    async def create(self, **req):
        name = req["tools"][0]["name"]
        if name == "post_position":
            out = {"stance": "file", "confidence": 0.8, "ready_to_close": True, "take": "x",
                   "claims": [{"text": "The listing describes the item as bone.", "evidence_ids": ["E0"]}]}
        elif name == "report_screening":
            out = {"score": 0.7, "suspicious": True, "reason": "Price is far above bone."}
        elif name == "report_material":
            n = sum(1 for b in req["messages"][0]["content"] if isinstance(b, dict) and b.get("type") == "image")
            out = {"photos": [{"index": i, "material": "bone", "confidence": 0.6, "visible_features": ["grain"], "best_region": "x"} for i in range(n)]}
        else:
            out = {}
        usage = NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=2000, cache_creation_input_tokens=0)
        return NS(content=[NS(type="tool_use", name=name, input=out)], usage=usage)


async def test_tokens_and_cost_come_from_the_real_accounting_including_cache_tokens(world, monkeypatch):
    from deadlang import triage
    from deadlang.agntcy.transport import LocalTransport
    from deadlang.deliberation.agents import DeliberatingAgent
    monkeypatch.setattr(config, "MODEL_STRONG", "claude-sonnet-5-5")
    monkeypatch.setattr(config, "MODEL_TRIAGE", "claude-haiku-4-5-20251001")
    llm.set_client_for_tests(Scripted())
    try:
        agents = {role: DeliberatingAgent(role) for role in AGENTS}
        discovery = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
        specs = [SellerInventory(world.market), LinkedSellers(world.market), PriceChecker(world.market)]
        ev = fe.Evaluator("rt", world.market, LocalTransport({s.name: s for s in specs}, agents, discovery=discovery), discovery,
                          screen=triage.screen)
        with fe.collecting_costs(ev.costs):
            row = await ev.run_listing(item_by_id(world, "L0001"))
    finally:
        llm.set_client_for_tests(None)
    assert row["errors"] == []
    t, a = row["tokens"]["triage"], row["tokens"]["agents"]
    assert (t["input_tokens"], t["output_tokens"], t["calls"], t["cache_read_tokens"]) == (1000, 100, 1, 2000)
    assert a["calls"] >= 2 and a["cache_read_tokens"] == 2000 * a["calls"] and a["input_tokens"] == 1000 * a["calls"]
    # triage on Haiku 4.5 ($1 / $5): (1,000 + 0.1 x 2,000) in, 100 out
    assert row["cost_usd"]["triage"] == pytest.approx((1200 * 1 + 100 * 5) / 1e6)
    assert row["cost_usd"]["agents"] > 0 and row["cost_usd"]["total"] == pytest.approx(row["cost_usd"]["triage"] + row["cost_usd"]["agents"])


# ---------------------------------------------------------------- the run: resume, errors, limits

async def run(world, ev, items, **kw):
    lines = []
    summary = await fe.run_items(ev, items, run_id=ev.run_id, out=lines.append, **kw)
    return summary, lines


async def test_finished_listings_are_skipped_on_a_rerun_with_the_same_run_id(world):
    items = fe.select(pop(world), limit=4)
    summary, _ = await run(world, evaluator(world), items)
    assert summary.done == 4 and len(fe.read_rows("r1")) == 4
    ev2 = evaluator(world)
    summary2, _ = await run(world, ev2, fe.select(pop(world), limit=6))
    assert summary2.done == 2 and len(fe.read_rows("r1")) == 6                           # only the two new ones ran
    assert len(ev2.fake_triage.calls) == 2


async def test_a_listing_that_errored_is_retried_on_a_rerun(world):
    items = fe.select(pop(world), limit=2)
    await run(world, evaluator(world, fail=(COUNSEL,)), items)
    assert all(r["errors"] for r in fe.read_rows("r1").values())
    summary, _ = await run(world, evaluator(world), items)
    assert summary.done == 2 and not any(r["errors"] for r in fe.read_rows("r1").values())   # the newer good rows win


async def test_rows_go_to_one_file_per_run(world):
    await run(world, evaluator(world, run_id="alpha"), fe.select(pop(world), limit=2))
    await run(world, evaluator(world, run_id="beta"), fe.select(pop(world), limit=3))
    assert fe.rows_path("alpha").parent.name == "eval_rows" and fe.rows_path("alpha").name == "alpha.jsonl"
    assert len(fe.read_rows("alpha")) == 2 and len(fe.read_rows("beta")) == 3


async def test_a_budget_stop_saves_the_rows_and_stops_cleanly(world):
    summary, lines = await run(world, evaluator(world, budget=(UNDERCOVER,)), fe.select(pop(world), limit=6), concurrency=1)
    assert summary.stopped == "budget" and summary.done >= 1 and len(fe.read_rows("r1")) == summary.done
    assert len(fe.read_rows("r1")) < 6


async def test_max_usd_stops_before_the_next_listing_would_pass_it(world):
    ev = evaluator(world)

    async def priced(item, orig=ev.run_listing):
        row = await orig(item)
        row["cost_usd"] = {"triage": 0.01, "agents": 0.04, "total": 0.05}                 # every listing costs $0.05
        return row

    ev.run_listing = priced
    summary, lines = await run(world, ev, fe.select(pop(world), limit=10), concurrency=1, max_usd=0.12, per_listing_estimate=0.05)
    assert summary.done == 2 and summary.stopped == "max_usd"                            # $0.10 spent; a third would reach $0.15
    assert summary.spent == pytest.approx(0.10) and len(fe.read_rows("r1")) == 2
    assert any("max-usd" in l.lower() or "max_usd" in l.lower() for l in lines)


async def test_max_usd_counts_spend_already_in_the_rows_of_this_run_id(world):
    ev = evaluator(world)

    async def priced(item, orig=ev.run_listing):
        row = await orig(item)
        row["cost_usd"] = {"triage": 0.0, "agents": 0.05, "total": 0.05}
        return row

    ev.run_listing = priced
    await run(world, ev, fe.select(pop(world), limit=2), concurrency=1)                  # $0.10 spent in a first invocation
    summary, _ = await run(world, ev, fe.select(pop(world), limit=10), concurrency=1, max_usd=0.12, per_listing_estimate=0.05)
    assert summary.done == 0 and summary.stopped == "max_usd"


async def test_progress_and_spend_are_printed_every_ten_listings(world):
    ev = evaluator(world)
    _, lines = await run(world, ev, fe.select(pop(world), limit=12), concurrency=1)
    progress = [l for l in lines if l.startswith("[")]
    assert len(progress) == 1 and "10/12" in progress[0] and "$" in progress[0] and "errors" in progress[0]


async def test_concurrency_runs_listings_together(world):
    ev = evaluator(world)
    orig = ev.run_listing
    state = {"now": 0, "peak": 0}

    async def slow(item):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.02)
        state["now"] -= 1
        return await orig(item)

    ev.run_listing = slow
    await run(world, ev, fe.select(pop(world), limit=6), concurrency=3)
    assert state["peak"] == 3


# ---------------------------------------------------------------- scoring

def row(lid, label, category, outcome, flagged=True, score=0.6, **kw):
    base = {"run_id": "s", "listing_id": lid, "label": label, "category": category, "language": "en", "ship_from": "US-CA",
            "country": "US", "material": "bone", "triage": {"score": score, "flagged": flagged, "reason": "r"},
            "outcome": outcome, "rounds": 1, "stop_reason": "unanimous", "agents_ran": list(AGENTS), "sat_out": [],
            "case_officer_abstained": False,
            "claims": {a: {"made": 4, "rejected": 1} for a in AGENTS},
            "tokens": {"triage": {"input_tokens": 100, "output_tokens": 10, "calls": 1, "cache_read_tokens": 0, "cache_write_tokens": 0},
                       "agents": {"input_tokens": 10_000, "output_tokens": 1_000, "calls": 8, "cache_read_tokens": 5_000, "cache_write_tokens": 500}},
            "cost_usd": {"triage": 0.001, "agents": 0.05, "total": 0.051}, "duration_s": {"triage": 1, "agents": 9, "total": 10},
            "errors": [], "warnings": []}
    base.update(kw)
    return base


def sample_rows():
    return [
        row("P1", True, "ivory", "FILE", flagged=True, score=0.9),
        row("P2", True, "ivory", "WATCHLIST", flagged=True, score=0.4),
        row("P3", True, "ivory", "CONTESTED", flagged=True, score=0.3),
        row("P4", True, "ivory", "DISMISS", flagged=False, score=0.1),                 # missed by the agents, and cleared by triage
        row("P5", True, "ivory", "FILE", flagged=False, score=0.12),                   # agents catch it, triage would have cleared it
        row("N1", False, "legal_bone", "DISMISS", flagged=False, score=0.05, material="bone"),
        row("N2", False, "legal_bone", "FILE", flagged=True, score=0.7, material="bone"),
        row("N3", False, "legal_resin", "DISMISS", flagged=False, score=0.02, material="resin", language="vi", ship_from="VN", country="VN"),
        row("N4", False, "tagua", "CONTESTED", flagged=True, score=0.5, material="tagua"),
        row("N5", False, "other_legal", "WATCHLIST", flagged=False, score=0.08, material="wood", sat_out=[OFFICER], case_officer_abstained=True,
            agents_ran=[UNDERCOVER, COUNSEL]),
        row("E1", True, "ivory", "FILE", errors=["agent counsel: timeout"]),         # an error: excluded from every number
    ]


def test_errors_are_excluded_and_counted():
    result = fe.score_rows(sample_rows(), threshold=0.2)
    assert result["population"]["n_scored"] == 10 and result["population"]["n_errors"] == 1
    assert result["population"]["error_ids"] == ["E1"]
    assert result["population"]["n_positives"] == 5 and result["population"]["n_negatives"] == 5


def test_sonnet_all_catch_false_accusation_and_escalation_with_counts():
    a = fe.score_rows(sample_rows(), threshold=0.2)["configs"]["sonnet_all"]
    assert a["catch"]["count"] == 3 and a["catch"]["n"] == 5 and a["catch"]["text"] == "3 of 5"      # FILE or WATCHLIST: P1, P2, P5
    assert a["catch"]["rate"] == 0.6
    assert a["false_accusation"]["text"] == "1 of 5"                                                  # N2 filed
    assert a["escalation"]["text"] == "2 of 10"                                                       # P3 and N4 contested
    assert a["outcomes_on_positives"] == {"FILE": 2, "WATCHLIST": 1, "CONTESTED": 1, "DISMISS": 1}
    assert a["outcomes_on_negatives"] == {"DISMISS": 2, "FILE": 1, "CONTESTED": 1, "WATCHLIST": 1}


def test_tiered_clears_what_triage_clears_and_keeps_the_agents_outcome_otherwise():
    t = fe.score_rows(sample_rows(), threshold=0.2)["configs"]["tiered"]
    # P4 (0.1, not flagged) and P5 (0.12, not flagged) are cleared; so are N1, N3, N5 (scores < 0.2, not flagged)
    assert t["catch"]["text"] == "2 of 5"                                  # P1 FILE and P2 WATCHLIST survive; P5's catch is lost to triage
    assert t["false_accusation"]["text"] == "1 of 5"                       # N2 still filed
    assert t["outcomes_on_positives"] == {"FILE": 1, "WATCHLIST": 1, "CONTESTED": 1, "CLEARED": 2}
    assert t["cleared_by_triage"]["text"] == "5 of 10"
    assert t["escalation"]["text"] == "2 of 10"


def test_the_models_own_flag_keeps_a_listing_even_below_the_threshold():
    rows = [row("P1", True, "ivory", "FILE", flagged=True, score=0.01), row("N1", False, "tagua", "DISMISS", flagged=False, score=0.01)]
    t = fe.score_rows(rows, threshold=0.2)["configs"]["tiered"]
    assert t["catch"]["text"] == "1 of 1" and t["cleared_by_triage"]["text"] == "1 of 2"


def test_tokens_and_cost_per_case_include_triage_only_when_it_ran_in_that_config():
    r = fe.score_rows(sample_rows(), threshold=0.2)["configs"]
    s, t = r["sonnet_all"], r["tiered"]
    assert s["per_case"]["cost_usd"] == pytest.approx(0.05) and s["per_case"]["input_tokens"] == 10_000
    assert s["per_case"]["cache_read_tokens"] == 5_000 and s["per_case"]["cache_write_tokens"] == 500 and s["per_case"]["output_tokens"] == 1_000
    assert s["total_cost_usd"] == pytest.approx(0.5)
    # tiered: every listing pays triage; only the 5 that passed pay the agents too
    assert t["total_cost_usd"] == pytest.approx(10 * 0.001 + 5 * 0.05)
    assert t["per_case"]["cost_usd"] == pytest.approx((10 * 0.001 + 5 * 0.05) / 10)
    assert t["per_case"]["input_tokens"] == pytest.approx((10 * 100 + 5 * 10_000) / 10)


def test_the_triage_recall_sweep_covers_005_to_05_with_counts():
    sweep = fe.score_rows(sample_rows(), threshold=0.2)["triage_sweep"]
    assert [s["threshold"] for s in sweep] == [round(0.05 * i, 2) for i in range(1, 11)]
    at = {s["threshold"]: s for s in sweep}
    # positives: P1 .9 flag, P2 .4 flag, P3 .3 flag, P4 .1 no flag, P5 .12 no flag (flags are the raw model flags)
    assert at[0.05]["recall"]["text"] == "5 of 5"                       # even P4 (0.1) passes at 0.05
    assert at[0.15]["recall"]["text"] == "3 of 5"                       # P1, P2, P3 flagged; P4 and P5 cleared
    assert at[0.5]["recall"]["text"] == "3 of 5"
    assert at[0.05]["cleared"]["count"] == 1 and at[0.05]["cleared"]["n"] == 10        # only N3 (0.02) is below 0.05 and unflagged
    assert at[0.5]["cleared"]["count"] == 5 and at[0.5]["cleared"]["text"] == "5 of 10"
    assert at[0.2]["is_current_threshold"] is True


def test_the_sweep_never_lets_recall_rise_as_the_threshold_rises():
    recalls = [s["recall"]["count"] for s in fe.score_rows(sample_rows(), threshold=0.2)["triage_sweep"]]
    assert recalls == sorted(recalls, reverse=True)


def test_subgroups_print_n_and_flag_small_groups():
    sub = fe.score_rows(sample_rows(), threshold=0.2)["subgroups"]
    assert set(sub) == {"language", "country", "material"}
    vi = sub["language"]["vi"]
    assert vi["n"] == 1 and vi["n_pos"] == 0 and vi["n_neg"] == 1
    assert vi["sonnet_all"]["false_accusation"]["too_small_to_headline"] is True
    assert vi["sonnet_all"]["miss"]["text"] == "0 of 0" and vi["sonnet_all"]["miss"]["rate"] is None
    bone = sub["material"]["bone"]
    assert bone["n"] == 7 and bone["n_pos"] == 5 and bone["n_neg"] == 2
    assert bone["sonnet_all"]["miss"] == {"count": 2, "n": 5, "rate": 0.4, "text": "2 of 5", "too_small_to_headline": True}   # n < 10
    assert sub["country"]["VN"]["n"] == 1


def test_a_group_with_ten_or_more_is_allowed_to_headline():
    rows = [row(f"P{i}", True, "ivory", "FILE") for i in range(10)]
    miss = fe.score_rows(rows, threshold=0.2)["subgroups"]["language"]["en"]["sonnet_all"]["miss"]
    assert miss["n"] == 10 and miss["too_small_to_headline"] is False


def test_how_often_the_case_officer_sat_out_overall_and_by_label_and_category():
    s = fe.score_rows(sample_rows(), threshold=0.2)["case_officer_sat_out"]
    assert s["overall"]["text"] == "1 of 10"
    assert s["by_label"]["positive"]["text"] == "0 of 5" and s["by_label"]["negative"]["text"] == "1 of 5"
    assert s["by_category"]["other_legal"]["text"] == "1 of 1" and s["by_category"]["ivory"]["text"] == "0 of 5"


def test_claim_quality_is_the_rejection_rate_per_agent():
    cq = fe.score_rows(sample_rows(), threshold=0.2)["claim_quality"]
    assert cq[UNDERCOVER]["made"] == 40 and cq[UNDERCOVER]["rejected"] == 10 and cq[UNDERCOVER]["rejection_rate"] == 0.25
    assert cq[UNDERCOVER]["listings"] == 10
    assert cq[OFFICER]["listings"] == 9 and cq[OFFICER]["made"] == 36                  # the listing where it sat out is not counted


def test_scoring_nothing_is_not_an_error():
    result = fe.score_rows([], threshold=0.2)
    assert result["population"]["n_scored"] == 0 and result["configs"]["sonnet_all"]["catch"]["rate"] is None


# ---------------------------------------------------------------- writing results/eval.json

def test_new_results_are_added_under_one_key_and_the_existing_shape_is_kept(world):
    results = config.REPO_ROOT / "results"
    results.mkdir(parents=True)
    old = {"A": {"n_pos": 3, "caught": 1}, "B": {"n_pos": 3}, "C": {"n_pos": 3, "escalated_rate": 0.1}, "examples": {"c_caught_b_missed": ["L1"]}}
    (results / "eval.json").write_text(json.dumps(old))
    fe.write_eval(fe.score_rows(sample_rows(), threshold=0.2), run_id="r9")
    out = json.loads((results / "eval.json").read_text())
    assert {k: out[k] for k in old} == old                                              # untouched
    assert list(set(out) - set(old)) == ["full_eval"] and out["full_eval"]["run_id"] == "r9"


def test_eval_json_is_created_when_there_is_none(world):
    fe.write_eval(fe.score_rows(sample_rows(), threshold=0.2), run_id="r9")
    assert "full_eval" in json.loads((config.REPO_ROOT / "results" / "eval.json").read_text())


def test_a_second_scoring_replaces_the_first_full_eval_key(world):
    fe.write_eval(fe.score_rows(sample_rows(), threshold=0.2), run_id="r1")
    fe.write_eval(fe.score_rows(sample_rows()[:3], threshold=0.2), run_id="r2")
    out = json.loads((config.REPO_ROOT / "results" / "eval.json").read_text())
    assert out["full_eval"]["run_id"] == "r2" and out["full_eval"]["population"]["n_scored"] == 3


# ---------------------------------------------------------------- command line

def parse(*argv):
    from deadlang.eval import run_eval
    return run_eval.build_parser().parse_args(list(argv))


def test_the_old_flags_still_parse_and_pick_the_old_mode():
    from deadlang.eval import run_eval
    a = parse("--modes", "A,C", "--limit", "4")
    assert a.modes == "A,C" and a.limit == 4 and not run_eval.is_full_mode(a)
    assert not run_eval.is_full_mode(parse())


@pytest.mark.parametrize("flags", [["--full"], ["--dry-run"], ["--stratified", "30"], ["--max-usd", "5"], ["--run-id", "x"],
                                   ["--yes"], ["--score-only", "--run-id", "x"], ["--concurrency", "2"]])
def test_any_new_flag_selects_the_full_set_eval(flags):
    from deadlang.eval import run_eval
    assert run_eval.is_full_mode(parse(*flags))


def run_cli(world, monkeypatch, argv, ask=lambda p: "y", models=("claude-haiku-4-5-20251001",), market=...):
    monkeypatch.setattr(config, "MODEL_TRIAGE", models[0])
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = asyncio.run(fe.main(parse(*argv), ask=ask, market=world.market if market is ... else market))
    return code, buf.getvalue()


def test_dry_run_prints_the_selection_models_estimate_and_my_commands_and_makes_no_calls(world, monkeypatch):
    monkeypatch.setattr(llm, "call_json", lambda **kw: pytest.fail("a dry run must not call a model"))
    code, out = run_cli(world, monkeypatch, ["--dry-run", "--stratified", "9"])
    assert code == 0
    assert "16 labeled listings" in out and "3 true positives" in out and "9 listings" in out
    for role in ("triage", "translator", "quick", "thorough", UNDERCOVER, COUNSEL, OFFICER):
        assert role in out
    assert "real API calls" in out and "Estimated cost" in out and "--run-id" in out
    assert not fe.rows_path("x").exists()


def test_the_dry_run_names_the_model_of_every_role(world, monkeypatch):
    monkeypatch.setattr(config, "MODEL_STRONG", "strong-test")
    monkeypatch.setattr(config, "MODEL_FAST", "claude-haiku-fast")
    code, out = run_cli(world, monkeypatch, ["--dry-run", "--limit", "3"], models=("claude-haiku-tri",))
    lines = {l.split()[0]: l for l in out.splitlines() if l.startswith("  ") and "claude" in l or "strong-test" in l}
    assert "claude-haiku-tri" in out and "strong-test" in out and "claude-haiku-fast" in out


def test_the_run_stops_when_triage_is_not_on_haiku_even_for_a_dry_run(world, monkeypatch):
    code, out = run_cli(world, monkeypatch, ["--dry-run"], models=("claude-sonnet-5-5",))
    assert code == 2 and "STOP" in out and "Haiku" in out and "DL_MODEL_TRIAGE" in out
    assert "Estimated" not in out


def test_declining_the_question_makes_no_calls_and_writes_nothing(world, monkeypatch):
    monkeypatch.setattr(llm, "call_json", lambda **kw: pytest.fail("declined: no calls"))
    code, out = run_cli(world, monkeypatch, ["--run-id", "nope", "--limit", "3"], ask=lambda p: "n")
    assert code == 1 and "No calls were made" in out and not fe.rows_path("nope").exists()


def test_score_only_reads_the_rows_scores_them_and_makes_no_calls(world, monkeypatch):
    path = fe.rows_path("sc")
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in sample_rows()))
    code, out = run_cli(world, monkeypatch, ["--score-only", "--run-id", "sc"], models=("claude-sonnet-5-5",))   # no Haiku guard: no model runs
    assert code == 0
    full = json.loads((config.REPO_ROOT / "results" / "eval.json").read_text())["full_eval"]
    assert full["run_id"] == "sc" and full["population"]["n_scored"] == 10
    assert "catch" in out.lower() and "3 of 5" in out


def test_score_only_needs_a_run_id_and_rows(world, monkeypatch):
    assert run_cli(world, monkeypatch, ["--score-only"])[0] == 2
    code, out = run_cli(world, monkeypatch, ["--score-only", "--run-id", "missing"])
    assert code == 2 and "no rows" in out.lower()


def test_a_real_run_with_yes_runs_scores_and_writes_everything(world, monkeypatch):
    ev = evaluator(world, run_id="go")
    monkeypatch.setattr(fe, "build_evaluator", lambda run_id, market: ev)
    code, out = run_cli(world, monkeypatch, ["--run-id", "go", "--yes", "--limit", "5", "--concurrency", "1"])
    assert code == 0 and len(fe.read_rows("go")) == 5
    assert json.loads((config.REPO_ROOT / "results" / "eval.json").read_text())["full_eval"]["run_id"] == "go"
    assert "Spend" in out or "spend" in out


# ---------------------------------------------------------------- the real CLI path: real local market, stub model client

@pytest.fixture
def real_singletons(world, monkeypatch):
    """Files on disk for the real local marketplace, and fresh process-wide singletons (market, discovery, transport)."""
    from deadlang.agntcy import discovery as disc, transport as trans
    from deadlang.marketplace import client as mclient
    (world.data / "sellers.jsonl").write_text("".join(make_seller(f"S{i}").model_dump_json() + "\n" for i in range(1, 17)))
    monkeypatch.delenv("MARKETPLACE_MODE", raising=False)
    monkeypatch.setattr(config, "TRANSPORT", "local")
    monkeypatch.setattr(config, "DISCOVERY", "local")
    for mod, name in ((mclient, "_client"), (disc, "_discovery"), (trans, "_transport")):
        monkeypatch.setattr(mod, name, None)
    monkeypatch.setattr(config, "MODEL_STRONG", "claude-sonnet-5-5")
    monkeypatch.setattr(llm, "usage_detail_hook", None)
    return world


def test_the_real_cli_path_runs_two_listings_end_to_end_with_the_real_local_market(real_singletons, monkeypatch):
    llm.set_client_for_tests(Scripted())
    try:
        code, out = run_cli(real_singletons, monkeypatch,
                            ["--run-id", "cli", "--yes", "--limit", "2", "--concurrency", "1"], market=None)
    finally:
        llm.set_client_for_tests(None)
    assert code == 0, out
    rows = fe.read_rows("cli")
    assert sorted(rows) == ["L0001", "L0002"]
    for r in rows.values():
        assert r["errors"] == [], r["errors"]
        assert r["outcome"] in ("FILE", "WATCHLIST", "DISMISS", "CONTESTED") and r["agents_ran"]
        assert r["tokens"]["triage"]["calls"] == 1 and r["tokens"]["agents"]["calls"] >= 2    # the usage hook is installed
        assert r["cost_usd"]["total"] > 0
    assert json.loads((config.REPO_ROOT / "results" / "eval.json").read_text())["full_eval"]["run_id"] == "cli"
    assert llm.usage_detail_hook is None                                                       # and put back afterwards


def test_a_crashed_run_leaves_error_rows_that_a_resume_retries(real_singletons, monkeypatch):
    fe.append_row("cli2", {**sample_rows()[0], "listing_id": "L0001", "errors": ["agents: AttributeError"]})
    fe.append_row("cli2", {**sample_rows()[0], "listing_id": "L0002", "errors": []})
    llm.set_client_for_tests(Scripted())
    try:
        code, out = run_cli(real_singletons, monkeypatch, ["--run-id", "cli2", "--yes", "--limit", "2", "--concurrency", "1"], market=None)
    finally:
        llm.set_client_for_tests(None)
    assert code == 0 and "Resuming: 1 already finished" in out
    rows = fe.read_rows("cli2")
    assert rows["L0001"]["errors"] == [] and rows["L0001"]["tokens"]["agents"]["calls"] >= 2   # retried
    assert rows["L0002"]["cost_usd"] == sample_rows()[0]["cost_usd"]                           # the finished one was not rerun
