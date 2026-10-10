"""Legal Table: looks up a fixed, sourced table (data/reference/legal.json). Code only, no judgment."""
from __future__ import annotations

import json

from deadlang.schemas import EvidenceDraft, SpecialistCall, SpecialistReply


def _first_sentence(text: str) -> str:
    return text.split(". ")[0].rstrip(".")


class LegalTable:
    name = "deadlang-legal-table"
    capability = "legal_lookup"
    tier = "preferred"

    def __init__(self, market):
        self.market = market
        self._table: dict | None = None

    def _jurisdiction(self, ship_from: str) -> str:
        if ship_from in self._table["jurisdictions"]:
            return ship_from
        return "US-federal" if ship_from == "US" or ship_from.startswith("US-") else "default"

    async def run(self, call: SpecialistCall) -> SpecialistReply:
        if self._table is None:
            self._table = json.loads(self.market.image_path("reference/legal.json").read_text())
        try:
            listing = await self.market.get_listing_snapshot(call.listing_id)
        except KeyError:
            return SpecialistReply(ok=False, error=f"unknown listing {call.listing_id}")
        material = call.params.get("material_hypothesis") or "elephant_ivory"
        species = self._table["species"].get(material)
        if species is None:
            return SpecialistReply(ok=False, error=f"no legal table entry for {material}")

        jurisdiction = self._jurisdiction(listing.ship_from)
        rule = self._table["jurisdictions"][jurisdiction]
        # For a non-US seller only the CITES sentence of the default row applies, so lead with that one.
        lead = rule["rule"].split(". ")[-1].rstrip(".") if jurisdiction == "default" else _first_sentence(rule["rule"])

        def draft(summary: str, data: dict) -> EvidenceDraft:
            return EvidenceDraft(capability="legal_lookup", summary=summary, data=data, produced_by="code",
                                 specialist_name=self.name)

        return SpecialistReply(ok=True, drafts=[
            draft(f"CITES listing for {species['common_name']}: {_first_sentence(species['cites'])}.",
                  {"material_hypothesis": material, **species}),
            draft(f"{lead} (applies because the item ships from {listing.ship_from}).",
                  {"material_hypothesis": material, "jurisdiction": jurisdiction, "ship_from": listing.ship_from,
                   **rule}),
        ])
