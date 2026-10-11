"""Translator (plan 03 Task 9): puts a non-English listing into plain English so the agents can cite it."""
from __future__ import annotations

from typing import Any

from deadlang import config, llm, untrusted
from deadlang.llm import BudgetExceeded
from deadlang.schemas import EvidenceDraft, SpecialistCall, SpecialistReply

SCHEMA_NAME = "report_translation"
MAX_PHRASES = 5
SYSTEM = ("Translate the marketplace listing to plain English. Then list up to 5 notable phrases from the "
          "original whose literal meaning matters for understanding what is being sold (materials, age, "
          "origin, quantity, payment or contact instructions). Do not judge legality. " + untrusted.RULE)

SCHEMA = {
    "type": "object",
    "properties": {
        "title_en": {"type": "string"},
        "description_en": {"type": "string"},
        "notable_phrases": {"type": "array", "maxItems": MAX_PHRASES, "items": {
            "type": "object",
            "properties": {"original": {"type": "string"}, "literal_en": {"type": "string"}},
            "required": ["original", "literal_en"]}},
    },
    "required": ["title_en", "description_en", "notable_phrases"],
}

LANGUAGE_NAMES = {
    "vi": "Vietnamese", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "th": "Thai", "id": "Indonesian",
    "ms": "Malay", "tl": "Tagalog", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese",
    "it": "Italian", "ru": "Russian", "ar": "Arabic", "nl": "Dutch",
}


def _clean_phrases(raw: Any) -> list[dict]:
    phrases = []
    for p in raw or []:
        if isinstance(p, dict) and p.get("original") and p.get("literal_en"):
            phrases.append({"original": str(p["original"]), "literal_en": str(p["literal_en"])})
    return phrases[:MAX_PHRASES]


class Translator:
    name = "deadlang-translator"
    capability = "translation"
    tier = "preferred"

    def __init__(self, market: Any):
        self.market = market
        self.model = config.MODEL_TRIAGE      # translation runs on the cheap model, like triage

    async def run(self, call: SpecialistCall) -> SpecialistReply:
        listing = await self.market.get_listing_snapshot(call.listing_id)
        if listing.language == "en":
            # Answer rather than fail: an agent asked, and a bare "already_english" error reads as a broken specialist
            # in the UI. No model call.
            draft = EvidenceDraft(capability="translation", produced_by="code", specialist_name=self.name,
                                  summary="The listing is already in English, so there is nothing to translate; "
                                          "the listing text on the board is the seller's own words.",
                                  data={"listing_id": listing.id, "language_code": "en", "already_english": True})
            return SpecialistReply(ok=True, drafts=[draft])
        language = LANGUAGE_NAMES.get(listing.language, listing.language)
        user = (f"Listing language: {language}\n"
                + untrusted.wrap(f"Title: {listing.title}\nDescription: {listing.description}", marker=untrusted.boundary()))
        try:
            out = await llm.call_json(model=self.model, system=SYSTEM, user=user, schema_name=SCHEMA_NAME,
                                      schema=SCHEMA, case_id=call.case_id, max_tokens=1500)
        except BudgetExceeded:
            return SpecialistReply(ok=False, error="budget")
        title_en = str(out.get("title_en") or "")
        data = {"listing_id": listing.id, "source_language": language, "language_code": listing.language,
                "title_en": title_en, "description_en": str(out.get("description_en") or ""),
                "notable_phrases": _clean_phrases(out.get("notable_phrases"))}
        draft = EvidenceDraft(capability="translation", summary=f'Translated from {language}: "{title_en}".',
                              data=data, produced_by="model", confidence=None, specialist_name=self.name)
        return SpecialistReply(ok=True, drafts=[draft])
