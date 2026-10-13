"""Bounds on the agents' discussion: rounds, turns per round, agent calls per case, early stop when nobody moves,
the Case Officer's closing call, and a compact transcript. Stub agents only."""
import asyncio

import pytest

from deadlang import config
from deadlang.api.events import EventBus
from deadlang.deliberation.facilitator import AGENTS, MAX_AGENT_CALLS_PER_CASE, Facilitator
from deadlang.schemas import Challenge, Claim, Rebuttal, StancePost
from tests.fakes import FakeDiscovery, FakeMarket

CLAIM = "Listed at $1,450."
NEXT = {"undercover": "counsel", "counsel": "case_officer", "case_officer": "undercover"}


class Agents:
    """Every agent answers every turn with a valid post; `stance(agent, turn)` decides its stance. Each post asks the
    next agent a question, so somebody always has a reason to speak again."""

    def __init__(self, stance, delay=0.0):
        self.stance, self.delay = stance, delay
        self.turns: list[tuple[str, object]] = []          # (agent, DeliberationTurn), in call order
        self.repairs = 0
        self.fac = None
        self.per_round: dict[tuple[int, str], int] = {}
        self.live = self.peak = 0

    def _post(self, a, turn):
        prev = turn.your_previous
        s = self.stance(a, turn.round)
        moved = prev is not None and prev.stance != s
        return StancePost(agent=a, round=turn.round, stance=s, confidence=0.6,
                          claims=[Claim(text=CLAIM, evidence_ids=["E0"])],
                          rebuttal=Rebuttal(target_agent=NEXT[a], target_claim=CLAIM, response="No.") if turn.round > 1 else None,
                          challenge=None if turn.final_decision else Challenge(target_agent=NEXT[a], question=f"why {turn.round}?"),
                          changed_because="E0 again" if moved else None, changed_because_evidence=["E0"] if moved else [],
                          take="t")

    async def broadcast_turns(self, turns, timeout=90.0):
        (a, turn), = turns.items()
        self.turns.append((a, turn))
        if self.fac is not None and not turn.final_decision:
            st = next(iter(self.fac._running.values()))
            key = (st.round, a)
            self.per_round[key] = self.per_round.get(key, 0) + 1
        self.live += 1
        self.peak = max(self.peak, self.live)
        await asyncio.sleep(self.delay)
        self.live -= 1
        return {a: self._post(a, turn)}

    async def call_agent(self, agent, turn, timeout=90.0):
        self.repairs += 1
        return self._post(agent, turn)

    async def call_specialist(self, name, call, timeout=45.0):
        from deadlang.schemas import SpecialistReply
        return SpecialistReply(ok=True, drafts=[])


def setup(agents, **kw):
    bus = EventBus(runs_dir=None)
    fac = Facilitator(FakeMarket(), agents, FakeDiscovery(), bus, **kw)
    agents.fac = fac
    return fac, bus


def flip(a, turn):                                   # never converges: every agent changes its mind every turn
    return "file" if (turn + AGENTS.index(a)) % 2 else "dismiss"


def steady(a, turn):                                 # never moves: undercover files, the others want more
    return "file" if a == "undercover" else "need_more"


# ---------------------------------------------------------------- the round limit

@pytest.mark.parametrize("dynamic", [True, False])
async def test_the_discussion_stops_at_the_round_limit_without_an_error(dynamic):
    agents = Agents(flip)
    fac, bus = setup(agents, max_rounds=3, dynamic=dynamic, max_agent_calls=100)
    cf = await fac.run_case("C-1", "L0101")                                  # no exception
    assert cf.stop_reason == "max_rounds" and max(r for r, _ in agents.per_round) == 3
    assert cf.outcome not in ("FILE", "DISMISS")                             # out of room is never a clean verdict
    last_agent, last_turn = agents.turns[-1]
    assert last_agent == "case_officer" and "limit" in last_turn.final_decision    # the Case Officer closes
    assert [e.type for e in bus.history("C-1")][-1] == "case.ended"


async def test_the_closing_call_asks_for_no_more_checks():
    agents = Agents(flip)
    fac, _ = setup(agents, max_rounds=2, max_agent_calls=100)
    await fac.run_case("C-1", "L0101")
    closing = [t for a, t in agents.turns if t.final_decision]
    assert len(closing) == 1


async def test_no_agent_takes_more_than_two_turns_in_a_round_when_dynamic():
    agents = Agents(flip, delay=0.01)
    fac, _ = setup(agents, max_rounds=4, dynamic=True, max_agent_calls=100)
    await fac.run_case("C-1", "L0101")
    assert agents.per_round and max(agents.per_round.values()) <= 2


async def test_one_at_a_time_mode_runs_agents_in_order_one_turn_each_per_round():
    agents = Agents(flip, delay=0.01)
    fac, _ = setup(agents, max_rounds=2, dynamic=False, max_agent_calls=100)
    await fac.run_case("C-1", "L0101")
    assert agents.peak == 1 and max(agents.per_round.values()) == 1
    assert [a for a, t in agents.turns if not t.final_decision][:3] == ["undercover", "counsel", "case_officer"]


async def test_dynamic_mode_runs_agents_at_the_same_time():
    agents = Agents(flip, delay=0.02)
    fac, _ = setup(agents, max_rounds=1, dynamic=True, max_agent_calls=100)
    await fac.run_case("C-1", "L0101")
    assert agents.peak == 3


def test_dynamic_is_the_default_and_a_flag_turns_it_off(monkeypatch):
    assert Facilitator(None, None, None, None).dynamic is config.DYNAMIC
    monkeypatch.setattr(config, "DYNAMIC", False)
    assert Facilitator(None, None, None, None).dynamic is False
    assert Facilitator(None, None, None, None, dynamic=True).dynamic is True


# ---------------------------------------------------------------- the agent-call limit

@pytest.mark.parametrize("cap", [4, 7, MAX_AGENT_CALLS_PER_CASE])
async def test_total_agent_calls_never_pass_the_cap_and_hitting_it_is_not_an_error(cap):
    agents = Agents(flip)
    fac, _ = setup(agents, max_rounds=50, max_agent_calls=cap)
    cf = await fac.run_case("C-1", "L0101")
    assert len(agents.turns) + agents.repairs <= cap
    assert cf.stop_reason == "max_rounds" and cf.outcome not in ("FILE", "DISMISS")
    assert agents.turns[-1][1].final_decision                               # the call kept back for the closing decision


async def test_hitting_a_limit_is_logged_as_limit_reached(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="deadlang.facilitator")
    fac, _ = setup(Agents(flip), max_rounds=2, max_agent_calls=100)
    await fac.run_case("C-1", "L0101")
    assert any("limit reached" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- stop early when nobody moves

async def test_when_nobody_changes_position_in_a_round_the_case_officer_closes_at_once():
    agents = Agents(steady)
    fac, _ = setup(agents, max_rounds=4, max_agent_calls=100)
    cf = await fac.run_case("C-1", "L0101")
    assert cf.stop_reason == "no_movement" and max(r for r, _ in agents.per_round) == 2   # round 2 shows no movement
    assert agents.turns[-1][0] == "case_officer" and "stopped moving" in agents.turns[-1][1].final_decision
    assert cf.outcome == "WATCHLIST"


async def test_movement_keeps_the_discussion_going():
    def late_mover(a, turn):                     # counsel changes its mind in round 2, then everyone holds
        return "file" if a == "undercover" or (a == "counsel" and turn >= 2) else "need_more"

    agents = Agents(late_mover)
    fac, _ = setup(agents, max_rounds=4, dynamic=False, max_agent_calls=100)     # one turn per round: turn == round
    cf = await fac.run_case("C-1", "L0101")
    assert cf.stop_reason == "no_movement" and max(r for r, _ in agents.per_round) == 3   # round 2 moved, round 3 did not


async def test_a_unanimous_room_ends_without_a_closing_call():
    agents = Agents(lambda a, t: "file")
    fac, _ = setup(agents, max_rounds=4, max_agent_calls=100)
    cf = await fac.run_case("C-1", "L0101")
    assert cf.stop_reason == "unanimous" and cf.outcome == "FILE"
    assert not any(t.final_decision for _, t in agents.turns)


# ---------------------------------------------------------------- what agents re-read

async def test_earlier_rounds_are_one_line_stances_and_the_last_round_is_in_full():
    agents = Agents(flip)
    fac, _ = setup(agents, max_rounds=3, dynamic=False, max_agent_calls=100)
    await fac.run_case("C-1", "L0101")
    # the first turn of round 3 is the 7th call in one-at-a-time mode (3 per round)
    a, turn = agents.turns[6]
    by_round = {}
    for p in turn.transcript:
        by_round.setdefault(p.claims != [], []).append(p)
    full, compact = by_round.get(True, []), by_round.get(False, [])
    assert len(compact) == 3 and all(not p.claims and p.rebuttal is None and p.challenge is None for p in compact)   # round 1
    assert len(full) == 3 and all(p.claims for p in full)                                                          # round 2
    assert all(p.stance for p in compact)                                    # the stance is still there


@pytest.mark.parametrize("env,dynamic", [({}, False), ({"DL_EVAL_DYNAMIC": "0"}, False), ({"DL_EVAL_DYNAMIC": "1"}, True),
                                         ({"DL_DYNAMIC": "1"}, False)])
def test_evals_run_one_at_a_time_unless_dl_eval_dynamic_opts_in(monkeypatch, env, dynamic):
    from deadlang.eval import run_eval
    monkeypatch.setattr(config, "DYNAMIC", not dynamic)                       # start from the opposite, to see it set
    line = run_eval.set_eval_mode(env)
    assert config.DYNAMIC is dynamic
    assert line.startswith("Eval mode: DYNAMIC" if dynamic else "Eval mode: ONE AT A TIME") and "12 agent calls" in line
