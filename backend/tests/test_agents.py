import pytest
from pydantic import ValidationError

from deadlang import llm
from deadlang.deliberation.agents import DeliberatingAgent, build_user_message
from deadlang.schemas import DeliberationTurn, Evidence, PeerQuestion

E0 = Evidence(id="E0", case_id="C-1", capability="listing_snapshot", summary='Listing L1 for $1,450.',
              data={"title": "Old bone netsuke", "description": "From a family collection", "price_usd": 1450.0},
              produced_by="code", specialist_name="intake", requested_by="intake")


def turn(**kw):
    return DeliberationTurn(case_id="C-1", round=2, max_rounds=4, evidence=[E0], transcript=[], **kw)


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    async def call_json(**kwargs):
        calls.append(kwargs)
        return {"stance": "file", "confidence": 0.8, "claims": [{"text": "Priced at $1,450.", "evidence_ids": ["E0"]}]}

    monkeypatch.setattr(llm, "call_json", call_json, raising=False)
    return calls


async def test_agent_and_round_are_filled_and_schema_has_no_agent_round(fake_llm):
    post = await DeliberatingAgent("defender").handle(turn())
    assert (post.agent, post.round, post.stance) == ("defender", 2, "file")
    schema = fake_llm[0]["schema"]
    assert "agent" not in schema["properties"] and "round" not in schema["properties"]
    assert "agent" not in schema["required"] and "round" not in schema["required"]
    assert fake_llm[0]["schema_name"] == "post_position" and fake_llm[0]["case_id"] == "C-1"


async def test_system_prompt_is_role_plus_shared_rules(fake_llm):
    await DeliberatingAgent("buyer").handle(turn())
    s = fake_llm[0]["system"]
    assert s.startswith("You are the Buyer") and "ready_to_close" in s


async def test_repair_feedback_and_questions_reach_the_prompt(fake_llm):
    t = turn(repair_feedback=["number 1000 not found in cited evidence E1"],
             questions_for_you=[PeerQuestion(asker="buyer", question="Is price alone enough?")])
    await DeliberatingAgent("defender").handle(t)
    u = fake_llm[0]["user"]
    assert "# Fix these problems" in u and "number 1000 not found" in u and "Repost your full position" in u
    assert "Buyer asks: Is price alone enough?" in u
    assert "Round 2 of 4" in u and "Old bone netsuke" in u


def test_no_repair_section_by_default():
    u = build_user_message(turn())
    assert "# Fix these problems" not in u and "# Questions for you" not in u
    assert u.index("# Listing under review") < u.index("# Evidence board") < u.index("# This round")


async def test_bad_model_output_raises(monkeypatch):
    async def bad(**kwargs):
        return {"stance": "maybe", "confidence": 2, "claims": []}

    monkeypatch.setattr(llm, "call_json", bad, raising=False)
    with pytest.raises(ValidationError):
        await DeliberatingAgent("buyer").handle(turn())
