"""Price Checker: how this listing's price compares with listings of the same stated material. Code only."""
from __future__ import annotations

import math
import statistics

from deadlang.schemas import EvidenceDraft, SpecialistCall, SpecialistReply

MIN_COMPARABLES = 5


def _nearest_rank(sorted_values: list[float], pct: float) -> float:
    return sorted_values[max(1, math.ceil(pct / 100 * len(sorted_values))) - 1]


class PriceChecker:
    name = "deadlang-price-checker"
    capability = "price_check"
    tier = "preferred"

    def __init__(self, market):
        self.market = market

    async def run(self, call: SpecialistCall) -> SpecialistReply:
        try:
            target = await self.market.get_listing_snapshot(call.listing_id)   # still works after removal
        except KeyError:
            return SpecialistReply(ok=False, error=f"unknown listing {call.listing_id}")
        # Reconstructed listings are excluded so our planted cases cannot inflate the normal price.
        pool = [l for l in await self.market.all_active()
                if l.id != target.id and not l.is_reconstructed and l.price_usd > 0
                and l.origin == "demo"                     # the stored market is the reference, never live fetches
                and l.stated_material == target.stated_material]
        comps = [l for l in pool if l.item_type == target.item_type]
        weak = len(comps) < MIN_COMPARABLES
        if weak:
            comps = pool                                   # widen: same material, any item type

        price = round(target.price_usd)                    # every number in the summary is stored as shown
        data = {"listing_id": target.id, "price_usd": price, "stated_material": target.stated_material,
                "item_type": target.item_type, "n": len(comps), "median_usd": None, "p25_usd": None,
                "p75_usd": None, "ratio": None, "weak_comparison": weak,
                "comparable_ids": [l.id for l in comps[:10]],
                # The comparables nearest in price, for a "similar products" view.
                "similar": [{"id": l.id, "title": l.title, "price_usd": l.price_usd, "category": l.category}
                            for l in sorted(comps, key=lambda l: abs(l.price_usd - target.price_usd))[:5]]}
        if len(comps) < MIN_COMPARABLES:
            summary = (f"Only {len(comps)} comparable {target.stated_material} listings were found, too few to "
                       f"say whether this listing's price of ${price} is unusual.")
        else:
            prices = sorted(l.price_usd for l in comps)
            median = max(1, round(statistics.median(prices)))
            p25, p75 = round(_nearest_rank(prices, 25)), round(_nearest_rank(prices, 75))
            ratio = round(price / median, 1)
            data.update(median_usd=median, p25_usd=p25, p75_usd=p75, ratio=ratio)
            what = target.stated_material if weak else f"{target.stated_material} {target.item_type}"
            summary = (f"Comparable {what} listings (n={len(comps)}) have a median price of ${median} "
                       f"(middle range ${p25}–${p75}); this listing is ${price}, {ratio}x the median.")
            if weak:
                summary += " Weak comparison: matched on material only."
        return SpecialistReply(ok=True, drafts=[EvidenceDraft(
            capability="price_check", summary=summary, data=data, produced_by="code", specialist_name=self.name)])
