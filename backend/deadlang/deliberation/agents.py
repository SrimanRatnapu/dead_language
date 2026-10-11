"""DeliberatingAgent: one model call per turn that turns the board + transcript into a StancePost."""
from __future__ import annotations

import os
from pathlib import Path

from deadlang import llm
from deadlang.evidence.board import render_evidence
from deadlang.schemas import AgentName, DeliberationTurn, Evidence, StancePost

PROMPTS = Path(__file__).parent / "prompts"
SCHEMA_NAME = "post_position"


def _model() -> str:
    return os.getenv("DL_MODEL_STRONG", "claude-sonnet-5-5")


def post_schema() -> dict:
    """StancePost schema without `agent` and `round`; the code fills those in."""
    schema = StancePost.model_json_schema()
    for key in ("agent", "round", "abstained"):
        schema["properties"].pop(key, None)
    schema["required"] = [k for k in schema.get("required", []) if k not in ("agent", "round")]
    return schema


def render_post(p: StancePost) -> str:
    lines = [f"- {p.agent.replace("_", " ").title()} (round {p.round}): stance={p.stance}, confidence={p.confidence}"
             + (", ready_to_close" if p.ready_to_close else "")]
    lines += [f"    claim: {c.text} [{', '.join(c.evidence_ids)}]" for c in p.claims]
    if p.rebuttal:
        r = p.rebuttal
        lines.append(f"    rebuttal to {r.target_agent} on \"{r.target_claim}\": {r.response}")
    if p.challenge:
        lines.append(f"    question to {p.challenge.target_agent}: {p.challenge.question}")
    lines += [f"    asked for {q.capability}: {q.question} ({q.reason})" for q in p.requests]
    if p.changed_because:
        lines.append(f"    changed position because: {p.changed_because} [{', '.join(p.changed_because_evidence)}]")
    return "\n".join(lines)


def _listing_section(evidence: list[Evidence]) -> str:
    e0 = next((e for e in evidence if e.id == "E0"), None)
    if e0 is None:
        return "(no listing snapshot on the board)"
    d = e0.data
    return (f"{e0.summary}\nTitle: {d.get('title')}\nPrice: ${d.get('price_usd')}\n"
            f"Description: {d.get('description')}")


def build_user_message(turn: DeliberationTurn) -> str:
    parts = [
        "# Listing under review\n" + _listing_section(turn.evidence),
        "# Evidence board\n" + render_evidence(turn.evidence),
        "# What the other agents have said so far (including earlier in this round)\n"
        + ("\n".join(render_post(p) for p in turn.transcript) or "Nothing yet. You are speaking first."),
    ]
    if turn.questions_for_you:
        parts.append("# Questions for you\n" + "\n".join(f"- {q.asker.replace("_", " ").title()} asks: {q.question}"
                                                         for q in turn.questions_for_you))
    parts.append("# Your previous post\n" + (render_post(turn.your_previous) if turn.your_previous else "None."))
    parts.append(f"# This round\nRound {turn.round} of {turn.max_rounds}. Post your position.")
    if turn.repair_feedback:
        parts.append("# Fix these problems\n" + "\n".join(f"- {f}" for f in turn.repair_feedback)
                     + "\nRepost your full position with these fixed.")
    return "\n\n".join(parts)


class DeliberatingAgent:
    def __init__(self, name: AgentName):
        self.name = name
        self.system = (PROMPTS / f"{name}.md").read_text() + "\n\n" + (PROMPTS / "shared_rules.md").read_text()

    async def handle(self, turn: DeliberationTurn) -> StancePost:
        out = await llm.call_json(
            model=_model(), system=self.system, user=build_user_message(turn), schema_name=SCHEMA_NAME,
            schema=post_schema(), case_id=turn.case_id, max_tokens=1200, temperature=0.2)
        return StancePost.model_validate({**out, "agent": self.name, "round": turn.round, "abstained": False})
