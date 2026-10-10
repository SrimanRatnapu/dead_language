"""AgentCards for every agent (plan 03 Task 4). Capabilities live in skill tags, e.g. `capability:material_exam`."""
from __future__ import annotations

from dataclasses import dataclass

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from agntcy_app_sdk.semantic.a2a.transport_types import InterfaceTransport

from deadlang import config
from deadlang.schemas import AgentName

SLIM_HOST = "localhost:46357"


@dataclass(frozen=True)
class CardSpec:
    capability: str            # skill id; "deliberate" for the three deliberators
    tier: str                  # preferred | fallback
    produced_by: str           # code | model
    model: str                 # model id or "none"
    description: str
    skill_description: str


def _specs() -> dict[str, CardSpec]:
    strong, fast = config.MODEL_STRONG, config.MODEL_FAST
    deliberator = ("Takes a DeliberationTurn (evidence board, earlier posts, questions for it) "
                   "and returns one StancePost with claims citing evidence IDs.")
    return {
        "deadlang-price-checker": CardSpec(
            "price_check", "preferred", "code", "none",
            "Compares a listing's price with comparable legal items.",
            "Takes a listing ID; returns the price ratio against comparable sold items."),
        "deadlang-seller-inventory": CardSpec(
            "seller_inventory", "preferred", "code", "none",
            "Summarizes everything a seller has listed, including removed listings.",
            "Takes a listing ID and optional seller_id; returns counts and patterns in the seller's listings."),
        "deadlang-linked-sellers": CardSpec(
            "linked_sellers", "preferred", "code", "none",
            "Finds other seller accounts that reuse the same photos or wording.",
            "Takes a listing ID; returns seller IDs linked by matching photos or text."),
        "deadlang-legal-table": CardSpec(
            "legal_lookup", "preferred", "code", "none",
            "Looks up the trade rules for a material where the item ships from.",
            "Takes a listing ID and optional material_hypothesis; returns the species and jurisdiction rules."),
        "deadlang-examiner-thorough": CardSpec(
            "material_exam", "preferred", "model", strong,
            "Examines listing photos twice and reports the material only when both looks agree.",
            "Takes a listing ID and optional image_index; returns the apparent material per photo with confidence."),
        "deadlang-examiner-quick": CardSpec(
            "material_exam", "fallback", "model", fast,
            "Examines listing photos once with a faster model; confidence is capped at 0.6.",
            "Takes a listing ID and optional image_index; returns the apparent material per photo with confidence."),
        "deadlang-translator": CardSpec(
            "translation", "preferred", "model", fast,
            "Translates a non-English listing into plain English.",
            "Takes a listing ID; returns the English title, description and notable phrases."),
        # Situational agents: called only when the case calls for them. Cards only for now; the owner builds
        # the agent. Check produced_by / model below against what they actually build.
        "deadlang-photo-reuse": CardSpec(
            "photo_reuse", "preferred", "code", "none",
            "Finds other listings and sellers that use the same or near-identical photos. Call when the photos "
            "look like stock or catalogue images, or when the seller or its linked sellers show repeated items.",
            "Call when the photos may be reused. Takes a listing ID; returns the other listings and sellers "
            "whose photos match, with how close each match is."),
        "deadlang-provenance": CardSpec(
            "provenance_check", "preferred", "code", "none",
            "Checks an item's claimed age, origin or paperwork against what the listing actually shows. Call "
            "when the listing claims an antique date, period, or certificate.",
            "Call when the listing claims an age, origin or paperwork. Takes a listing ID; returns what is "
            "claimed and whether anything in the listing supports it."),
        "deadlang-exemption-reviewer": CardSpec(
            "exemption_review", "preferred", "model", strong,
            "Checks whether a legal exemption (for example antique age or pre-ban ownership) could apply, given "
            "the evidence. Call when the legal lookup shows an exemption exists and the listing makes a claim "
            "that could meet it.",
            "Call when an exemption might apply. Takes a listing ID and the legal evidence; returns which "
            "exemptions could apply and what proof each would need."),
        "deadlang-buyer": CardSpec(
            "deliberate", "preferred", "model", strong,
            "Reviews a case as an experienced buyer who knows prices and materials.", deliberator),
        "deadlang-defender": CardSpec(
            "deliberate", "preferred", "model", strong,
            "Reviews a case looking for the innocent explanation of a listing.", deliberator),
        "deadlang-caseload": CardSpec(
            "deliberate", "preferred", "model", strong,
            "Reviews a case for whether it is worth an investigator's limited time.", deliberator),
    }


SPECIALIST_NAMES: list[str] = [
    "deadlang-price-checker", "deadlang-seller-inventory", "deadlang-linked-sellers", "deadlang-legal-table",
    "deadlang-examiner-thorough", "deadlang-examiner-quick", "deadlang-translator",
]
# Not in ALL_AGENT_NAMES on purpose: that list is who is running, and discovery or the Directory would offer
# an agent that does not exist yet. Add a name to it when its owner has built the agent.
SITUATIONAL_NAMES: list[str] = ["deadlang-photo-reuse", "deadlang-provenance", "deadlang-exemption-reviewer"]
DELIBERATOR_NAMES: dict[AgentName, str] = {
    "buyer": "deadlang-buyer", "defender": "deadlang-defender", "caseload": "deadlang-caseload",
}
ALL_AGENT_NAMES: list[str] = SPECIALIST_NAMES + list(DELIBERATOR_NAMES.values())


def card_for(name: str) -> AgentCard:
    spec = _specs()[name]
    url = f"slim://{SLIM_HOST}/default/default/{name}"
    skill = AgentSkill(
        id=spec.capability, name=spec.capability, description=spec.skill_description,
        tags=[f"capability:{spec.capability}", f"tier:{spec.tier}",
              f"produced_by:{spec.produced_by}", f"model:{spec.model}"])
    return AgentCard(
        name=name, description=spec.description, version="1.0.0", url=url,
        capabilities=AgentCapabilities(), default_input_modes=["text"], default_output_modes=["text"],
        preferred_transport=InterfaceTransport.SLIM_PATTERNS,
        additional_interfaces=[AgentInterface(transport=InterfaceTransport.SLIM_PATTERNS, url=url)],
        skills=[skill])


def card_tags(card: AgentCard) -> dict[str, str]:
    """`{"capability": ..., "tier": ..., "produced_by": ..., "model": ...}` from the card's skill tags."""
    tags: dict[str, str] = {}
    for skill in card.skills:
        for tag in skill.tags:
            key, _, value = tag.partition(":")
            tags.setdefault(key, value)
    return tags


def names_for_capability(capability: str) -> list[str]:
    """Who *should* offer a capability (static); discovery still checks who is registered and healthy."""
    return [n for n, s in _specs().items() if s.capability == capability]
