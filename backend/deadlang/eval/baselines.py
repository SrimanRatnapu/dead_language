"""Baselines for the evaluation: one model call each, no deliberation."""
from __future__ import annotations


from deadlang import config, llm
from deadlang.deliberation.validator import validate_post
from deadlang.evidence.board import EvidenceBoard, render_evidence
from deadlang.schemas import Listing, StancePost

SYSTEM = ("You review one marketplace listing for possible disguised elephant ivory. "
          "Decide whether to file it for human investigation or dismiss it. Keep the reason to one sentence.")

_DECISION = {"decision": {"type": "string", "enum": ["file", "dismiss"]},
             "confidence": {"type": "number", "minimum": 0, "maximum": 1},
             "reason": {"type": "string"}}
SCHEMA = {"type": "object", "properties": _DECISION, "required": list(_DECISION)}
SCHEMA_CLAIMS = {"type": "object", "required": [*_DECISION, "claims"], "properties": {
    **_DECISION, "claims": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "required": ["text", "evidence_ids"],
        "properties": {"text": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}}}}}


def _model() -> str:
    return config.MODEL_STRONG


async def listing_only(listing: Listing, case_id: str | None = None) -> dict:
    user = (f'Title: {listing.title}\nPrice: ${listing.price_usd:,.0f}\nStated material: {listing.stated_material}\n'
            f"Ships from: {listing.ship_from}\nDescription: {listing.description}")
    return await llm.call_json(model=_model(), system=SYSTEM, user=user, schema_name="report_decision",
                               schema=SCHEMA, case_id=case_id, max_tokens=1000)


async def single_agent_with_evidence(board: EvidenceBoard, listing_text: str,
                                     case_id: str | None = None) -> tuple[dict, int]:
    """Returns (decision dict with validated claims only, number of rejected claims)."""
    system = (SYSTEM + " Cite evidence ids (E0, E1, ...) for every claim; every number and quoted phrase "
              "must appear in the cited evidence. Never invent facts.")
    out = await llm.call_json(model=_model(), system=system,
                              user="# Evidence board\n" + render_evidence(board.all()),
                              schema_name="report_decision", schema=SCHEMA_CLAIMS, case_id=case_id, max_tokens=1500)
    as_post = StancePost(agent="undercover", round=1, stance=out["decision"], confidence=out["confidence"],
                         claims=out.get("claims", []))
    cleaned, rejections, _ = validate_post(as_post, board, listing_text, None, 1, [])
    return {**out, "claims": [c.model_dump() for c in cleaned.claims]}, len(rejections)
