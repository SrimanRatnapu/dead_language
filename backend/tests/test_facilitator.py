from deadlang.api.events import EventBus
from deadlang.deliberation.facilitator import Facilitator
from deadlang.schemas import Challenge, Rebuttal, SpecialistReply, SpecialistRequest
from tests.fakes import FakeDiscovery, FakeMarket, FakeTransport, draft, post


def reb(target):
    return Rebuttal(target_agent=target, target_claim="Listed at $1,450.", response="I disagree.")


def setup(transport, max_rounds=4):
    bus = EventBus(runs_dir=None)
    return Facilitator(FakeMarket(), transport, FakeDiscovery(), bus, max_rounds=max_rounds), bus


def types(bus, t=None):
    ev = [e for e in bus.history("C-1")]
    return [e for e in ev if e.type == t] if t else [e.type for e in ev]


async def test_unanimous_file_in_round_2_after_requested_exam_changes_a_mind():
    exam = SpecialistRequest(capability="material_exam", question="photo 2?", reason="base", params={"image_index": 2})
    t = FakeTransport(posts={
        ("undercover", 1): post("undercover", 1, "file"),
        ("counsel", 1): post("counsel", 1, "dismiss", requests=[exam]),
        ("case_officer", 1): post("case_officer", 1, "need_more"),
        ("undercover", 2): post("undercover", 2, "file", 0.9, rebuttal=reb("counsel")),
        ("counsel", 2): post("counsel", 2, "file", 0.7, rebuttal=reb("undercover"), changed_because="ivory grain",
                              changed_because_evidence=["E6"]),
        ("case_officer", 2): post("case_officer", 2, "file", 0.8, rebuttal=reb("counsel"), changed_because="n",
                              changed_because_evidence=["E6"]),
    })
    fac, bus = setup(t)
    cf = await fac.run_case("C-1", "L0101")
    assert (cf.outcome, cf.stop_reason, cf.rounds_used) == ("FILE", "unanimous", 2)
    e6 = next(e for e in cf.evidence if e.id == "E6")
    assert e6.capability == "material_exam" and e6.requested_by == "counsel"
    assert any(n == "deadlang-examiner-thorough" and c.params == {"image_index": 2} for n, c in t.calls)
    assert cf.tip_draft and "prepared for human review, not sent" in cf.tip_draft
    seqs = [e.seq for e in bus.history("C-1")]
    assert seqs == list(range(len(seqs)))                                   # (g) strictly increasing
    assert types(bus)[0] == "case.started" and types(bus)[-1] == "case.ended"


async def test_contested_after_max_rounds():
    def r(agent, rnd, stance, conf, target):
        return post(agent, rnd, stance, conf, challenge=Challenge(target_agent=target, question="why?"),
                    **({"rebuttal": reb(target)} if rnd > 1 else {}))
    posts = {}
    for rnd in range(1, 5):
        c = 0.4 + 0.15 * rnd
        posts[("undercover", rnd)] = r("undercover", rnd, "file", c, "counsel")
        posts[("counsel", rnd)] = r("counsel", rnd, "dismiss", c, "case_officer")
        posts[("case_officer", rnd)] = r("case_officer", rnd, "need_more", c, "undercover")
    fac, bus = setup(FakeTransport(posts=posts))
    cf = await fac.run_case("C-1", "L0101")
    # nobody moves in round 2, so the discussion stops there and the Case Officer makes the closing call
    assert (cf.outcome, cf.stop_reason) == ("CONTESTED", "no_movement") and cf.rounds_used <= 4
    assert "Outcome of agent review: CONTESTED" in cf.tip_draft


async def test_thorough_examiner_timeout_falls_back_to_quick():
    t = FakeTransport(timeouts={"deadlang-examiner-thorough"}, posts={
        (a, 1): post(a, 1, "dismiss") for a in ("undercover", "counsel", "case_officer")})
    fac, bus = setup(t)
    cf = await fac.run_case("C-1", "L0101")
    failed = types(bus, "specialist.failed")
    assert failed[0].payload["specialist_name"] == "deadlang-examiner-thorough"
    assert failed[0].payload["fallback"] == "deadlang-examiner-quick"
    assert [n for n, c in t.calls if c.capability == "material_exam"] == ["deadlang-examiner-thorough", "deadlang-examiner-quick"]
    assert any(e.capability == "material_exam" and e.specialist_name == "deadlang-examiner-quick" for e in cf.evidence)
    assert cf.outcome == "DISMISS" and "deadlang-examiner-thorough" in fac.discovery.unhealthy


async def test_invented_number_rejected_after_failed_repair():
    bad = [("Listed at $1,450.", ["E0"]), ("Bone netsuke sell for $1000.", ["E1"])]
    t = FakeTransport(posts={
        ("undercover", 1): post("undercover", 1, "file", claims=bad),
        ("counsel", 1): post("counsel", 1, "file"), ("case_officer", 1): post("case_officer", 1, "file")},
        repairs={("undercover", 1): post("undercover", 1, "file", claims=bad)})
    fac, bus = setup(t)
    cf = await fac.run_case("C-1", "L0101")
    rejected = types(bus, "claim.rejected")
    assert len(rejected) == 1 and rejected[0].payload["claim_text"] == "Bone netsuke sell for $1000."
    assert "number 1000" in rejected[0].payload["reasons"][0]
    assert len(t.repair_calls) == 1 and "Bone netsuke sell for $1000." in t.repair_calls[0][1].repair_feedback[0]
    buyer = next(p for p in cf.final_positions if p.agent == "undercover")
    assert [c.text for c in buyer.claims] == ["Listed at $1,450."]            # valid claim kept, bad one dropped


async def test_zero_valid_claims_downgrades_to_need_more():
    t = FakeTransport(posts={
        ("undercover", 1): post("undercover", 1, "file", claims=[("Invented $1000.", ["E0"])]),
        ("counsel", 1): post("counsel", 1, "file"), ("case_officer", 1): post("case_officer", 1, "file")},
        repairs={("undercover", 1): post("undercover", 1, "file", claims=[("Invented $1000.", ["E0"])])})
    fac, bus = setup(t)
    cf = await fac.run_case("C-1", "L0101")
    assert next(p for p in cf.final_positions if p.agent == "undercover").stance == "need_more"
    assert cf.outcome != "FILE"


async def test_listing_removed_mid_case_adds_notices_and_case_continues():
    t = FakeTransport(posts={(a, 1): post(a, 1, "file") for a in ("undercover", "counsel", "case_officer")})
    fac, bus = setup(t)

    async def remove(r):
        await fac.notify_listing_removed("L0101", "L0456")
        await fac.notify_listing_removed("L0101", "L0456")                  # duplicate call is ignored
    t.on_broadcast = remove
    cf = await fac.run_case("C-1", "L0101")
    notices = [e for e in cf.evidence if e.capability == "system_notice"]
    assert len(notices) == 2 and "removed by the seller" in notices[0].summary and "L0456" in notices[1].summary
    assert len(types(bus, "listing.removed")) == 1
    assert cf.outcome == "FILE"


async def test_budget_exceeded_in_round_2_stops_with_budget():
    t = FakeTransport(budget_in_round=2, posts={
        ("undercover", 1): post("undercover", 1, "file"), ("counsel", 1): post("counsel", 1, "dismiss"),
        ("case_officer", 1): post("case_officer", 1, "need_more", challenge=Challenge(target_agent="undercover", question="?"))})
    fac, bus = setup(t)
    cf = await fac.run_case("C-1", "L0101")
    assert cf.stop_reason == "budget" and types(bus, "budget.exceeded")
    assert cf.outcome == "CONTESTED" and cf.rounds_used == 2               # round-1 positions are preserved


async def test_only_triggered_agents_are_called_and_others_carry_forward():
    t = FakeTransport(posts={
        ("undercover", 1): post("undercover", 1, "file"), ("counsel", 1): post("counsel", 1, "dismiss"),
        ("case_officer", 1): post("case_officer", 1, "need_more", challenge=Challenge(target_agent="undercover", question="why?")),
        ("undercover", 2): post("undercover", 2, "file", rebuttal=reb("counsel"))})
    fac, bus = setup(t)
    cf = await fac.run_case("C-1", "L0101")
    assert t.broadcasts == [(1, ["undercover"]), (1, ["counsel"]), (1, ["case_officer"]), (2, ["undercover"])]
    assert [e.payload["agent"] for e in types(bus, "agent.thinking")] == ["undercover", "counsel", "case_officer", "undercover"]
    assert cf.stop_reason == "ready_to_close" and cf.outcome == "CONTESTED"
    assert len([e for e in types(bus, "stance.posted") if e.payload["post"]["round"] == 2]) == 1


async def test_specialist_request_caps_and_dedupe():
    reqs = [SpecialistRequest(capability="price_check", question="q", reason="r", params={"k": i}) for i in range(2)]
    dup = SpecialistRequest(capability="price_check", question="q", reason="r", params={"k": 0})
    t = FakeTransport(posts={
        ("undercover", 1): post("undercover", 1, "need_more", requests=reqs),
        ("counsel", 1): post("counsel", 1, "need_more", requests=[dup, SpecialistRequest(
            capability="legal_lookup", question="q", reason="r", params={"x": 1})]),
        ("case_officer", 1): post("case_officer", 1, "need_more", requests=[SpecialistRequest(
            capability="seller_inventory", question="q", reason="r", params={"x": 2})])})
    fac, bus = setup(t, max_rounds=1)
    await fac.run_case("C-1", "L0101")
    requested = [c for n, c in t.calls if c.params]
    # counsel's duplicate of undercover's k0 is merged; its legal_lookup runs; the officer's seller_inventory is the
    # fourth request this round, so the 3-per-round cap drops it and says so
    assert sorted(str(c.params) for c in requested) == sorted(map(str, [{"k": 0}, {"k": 1}, {"x": 1}]))
    dropped = [e.payload for e in types(bus, "specialist.failed") if e.payload["error"].startswith("request limit")]
    assert [(d["capability"], d["requested_by"], d["error"]) for d in dropped] == [
        ("seller_inventory", "case_officer", "request limit reached (3 per round)")]


async def test_precomputed_intake_is_reused_without_calling_specialists_again():
    t = FakeTransport(posts={(a, 1): post(a, 1, "file") for a in ("undercover", "counsel", "case_officer")})
    fac, bus = setup(t)
    st = await fac.run_intake("eval-intake", "L0101")
    n_calls = len(t.calls)
    assert n_calls == 5 and st.board.count() == 6
    cf = await fac.run_case("C-1", "L0101", intake=st)
    assert len(t.calls) == n_calls                                          # no new specialist calls
    assert [e.id for e in cf.evidence] == [e.id for e in st.board.all()] and cf.outcome == "FILE"
    assert all(e.case_id == "C-1" for e in cf.evidence)


async def test_relist_id_arriving_after_removal_adds_relist_notice_once():
    t = FakeTransport(posts={(a, 1): post(a, 1, "file") for a in ("undercover", "counsel", "case_officer")})
    fac, bus = setup(t)

    async def pause(r):
        await fac.notify_listing_removed("L0101", None)
        await fac.notify_listing_removed("L0101", "L0456")
        await fac.notify_listing_removed("L0101", "L0456")
    t.on_broadcast = pause
    cf = await fac.run_case("C-1", "L0101")
    notices = [e for e in cf.evidence if e.capability == "system_notice"]
    assert len(notices) == 2 and "L0456" in notices[1].summary
    assert [e.payload["relisted_as"] for e in types(bus, "listing.removed")] == [None, "L0456"]


async def test_later_agents_read_earlier_posts_in_the_same_round():
    seen = {}
    t = FakeTransport(posts={("undercover", 1): post("undercover", 1, "file"), ("counsel", 1): post("counsel", 1, "dismiss"),
                             ("case_officer", 1): post("case_officer", 1, "need_more")})
    orig = t.broadcast_turns

    async def spy(turns, timeout=90.0):
        (a, turn), = turns.items()
        seen[a] = [p.agent for p in turn.transcript]
        return await orig(turns, timeout)
    t.broadcast_turns = spy
    fac, _ = setup(t)
    await fac.run_case("C-1", "L0101")
    assert seen["undercover"] == [] and seen["counsel"] == ["undercover"] and seen["case_officer"] == ["undercover", "counsel"]


async def test_a_case_where_no_agent_answers_is_an_error_not_a_watchlist():
    import pytest
    t = FakeTransport(posts={(a, 1): "Error code: 401 - invalid x-api-key" for a in ("undercover", "counsel", "case_officer")})
    fac, _ = setup(t)
    with pytest.raises(RuntimeError, match="no agent answered.*401"):
        await fac.run_case("C-1", "L0101")


async def test_agents_think_at_the_same_time_and_a_specialist_answer_wakes_the_rest():
    import asyncio
    exam = SpecialistRequest(capability="price_check", question="q", reason="r", params={"k": 1})
    t = FakeTransport(posts={
        ("undercover", 1): post("undercover", 1, "need_more", requests=[exam]),
        ("counsel", 1): post("counsel", 1, "need_more"), ("case_officer", 1): post("case_officer", 1, "need_more")})
    live = peak = 0
    orig = t.broadcast_turns

    async def slow(turns, timeout=90.0):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        live -= 1
        return await orig(turns, timeout)

    t.broadcast_turns = slow
    fac, bus = setup(t)
    cf = await fac.run_case("C-1", "L0101")
    assert peak == 3                                                         # nobody waited for anybody
    first_turns = [e.payload["agent"] for e in types(bus, "agent.thinking")][:3]
    assert sorted(first_turns) == ["case_officer", "counsel", "undercover"]
    # the requested price check came back after the first posts, so every agent took a second look at it
    assert sorted(a for r, [a] in t.broadcasts if r == 2) == ["case_officer", "counsel", "undercover"]
    assert cf.stop_reason in ("ready_to_close", "max_rounds", "no_movement")
