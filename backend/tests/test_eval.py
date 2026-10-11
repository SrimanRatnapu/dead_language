from deadlang import llm
from deadlang.eval.run_eval import CollectBus, compute_metrics, merge_rows, run_listing, stance_changes_after_new_evidence
from deadlang.deliberation.facilitator import Facilitator
from tests.fakes import FakeDiscovery, FakeMarket, FakeTransport, post


def ev(i):
    return ("evidence.added", {"evidence": {"id": i}})


def posted(agent, cites):
    return ("stance.posted", {"post": {"agent": agent, "changed_because_evidence": cites}})


def test_stance_change_counts_only_evidence_added_after_the_agents_previous_post():
    events = [ev("E0"), posted("undercover", []), ev("E1"), posted("undercover", ["E1"]), posted("undercover", ["E1"]),
              posted("counsel", ["E0"])]
    # buyer r2 cites E1 (new since r1) -> counts; buyer r3 cites E1 (old) -> no; defender's first post cites E0 -> no
    assert stance_changes_after_new_evidence(events) == 2   # defender has no previous post, so E0 counts as new


def _row(lid, a, b, c):
    return {"listing_id": lid, "A": {"decision": a, "input_tokens": 10, "output_tokens": 5},
            "B": {"decision": b, "input_tokens": 20, "output_tokens": 5, "claims_rejected": 1},
            "C": {"decision": c, "input_tokens": 40, "output_tokens": 9, "claims_rejected": 2,
                  "stance_changes_after_new_evidence": 1}}


def test_metrics_and_examples():
    rows = [_row("P1", "DISMISS", "DISMISS", "FILE"), _row("P2", "FILE", "FILE", "CONTESTED"),
            _row("N1", "FILE", "FILE", "DISMISS"), _row("N2", "DISMISS", "DISMISS", "DISMISS")]
    m = compute_metrics(rows, {"P1": True, "P2": True, "N1": False, "N2": False})
    assert (m["A"]["caught"], m["A"]["false_accusations"], m["A"]["false_accusation_rate"]) == (1, 1, 0.5)
    assert (m["C"]["caught"], m["C"]["caught_or_escalated"], m["C"]["false_accusations"]) == (1, 2, 0)
    assert m["C"]["escalated_rate"] == 0.25 and m["B"]["claims_rejected_per_case"] == 1.0
    assert m["examples"] == {"c_caught_b_missed": ["P1"], "b_false_accusation_c_avoided": ["N1"]}


async def test_run_listing_all_modes_reuses_intake(monkeypatch):
    async def fake_call_json(**kw):
        return {"decision": "file", "confidence": 0.9, "reason": "r", "claims": []}
    monkeypatch.setattr(llm, "call_json", fake_call_json, raising=False)
    monkeypatch.setattr(llm, "usage_snapshot", lambda cid=None: {"input_tokens": 1, "output_tokens": 2, "calls": 1}, raising=False)
    t = FakeTransport(posts={(a, 1): post(a, 1, "file") for a in ("undercover", "counsel", "case_officer")})
    fac = Facilitator(FakeMarket(), t, FakeDiscovery(), CollectBus())
    row = await run_listing(fac, "L0101", {"A", "B", "C"})
    assert [row[m]["decision"] for m in "ABC"] == ["FILE", "FILE", "FILE"]
    assert len(t.calls) == 5      # intake ran once for B and C together


def test_resumed_modes_are_merged_not_overwritten():
    rows = [{"listing_id": "L1", "A": {"decision": "FILE"}}, {"listing_id": "L1", "B": {"decision": "DISMISS"}},
            {"listing_id": "L1", "A": {"decision": "DISMISS"}}]
    assert merge_rows(rows) == {"L1": {"listing_id": "L1", "A": {"decision": "DISMISS"}, "B": {"decision": "DISMISS"}}}
