"""Network Tracer: the seller's other listings, and other sellers linked by rare wording or reused photos.

Code only. Phrases are word 5-grams; photos are compared by perceptual hash.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from deadlang.schemas import EvidenceDraft, Listing, SpecialistCall, SpecialistReply

MAX_ITEMS = 12
NGRAM = 5
MAX_OTHER_SELLERS = 3        # a phrase is rare if at most this many OTHER sellers use it
MIN_SHARED_PHRASES = 2       # a phrase link needs this many shared rare phrases ...
MIN_PHRASE_WORDS = 8         # ... each at least this long. On real eBay data, shorter overlaps are template
                             # boilerplate ("import duties and taxes are"): 112 of 300 real listings matched
                             # under a bare two-5-gram rule, 4 under this one.
MAX_PHOTO_DISTANCE = 6       # Hamming distance between perceptual hashes
STOPWORDS = frozenset("""a an and are as at be been but by can do for from had has have i if in into is it its
me my no not of on or our so than that the their them then there these they this to up us was we were what when
which who will with you your""".split())


class SellerInventory:
    name = "deadlang-seller-inventory"
    capability = "seller_inventory"
    tier = "preferred"

    def __init__(self, market):
        self.market = market

    async def run(self, call: SpecialistCall) -> SpecialistReply:
        try:
            target = await self.market.get_listing_snapshot(call.listing_id)
            seller = await self.market.get_seller(call.params.get("seller_id") or target.seller_id)
        except KeyError as exc:
            return SpecialistReply(ok=False, error=f"unknown listing or seller {exc.args[0]}")
        items = await self.market.get_seller_inventory(seller.id)      # active + removed
        data = {
            "seller_id": seller.id, "seller_name": seller.name,
            "listing_count": len(items),
            "removed_count": sum(l.status == "removed" for l in items),
            "stated_material": target.stated_material, "item_type": target.item_type,
            "same_material_count": sum(l.stated_material == target.stated_material for l in items),
            "same_type_count": sum(l.item_type == target.item_type for l in items),
            "total_value_usd": round(sum(l.price_usd for l in items)),
            "items": [{"id": l.id, "title": l.title, "price_usd": l.price_usd, "stated_material": l.stated_material,
                       "item_type": l.item_type, "status": l.status} for l in items[:MAX_ITEMS]],
        }
        summary = (f"Seller {seller.name} has {data['listing_count']} listings ({data['removed_count']} removed); "
                   f"{data['same_material_count']} are described as {target.stated_material} and "
                   f"{data['same_type_count']} are {target.item_type} items, worth "
                   f"${data['total_value_usd']:,} in total.")
        return SpecialistReply(ok=True, drafts=[EvidenceDraft(
            capability="seller_inventory", summary=summary, data=data, produced_by="code",
            specialist_name=self.name)])


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", text.lower().replace("'", "").replace("’", "")).split()


def _token_runs(listing: Listing) -> list[list[str]]:
    """One token list per sentence, so a phrase never spans two sentences or the title and description.
    (Otherwise two common sentences that merely sit next to each other would look like a rare phrase.)"""
    sentences = re.split(r"[.!?;:\n]+", f"{listing.title}\n{listing.description}")
    return [tokens for tokens in map(_tokens, sentences) if tokens]


def _ngrams(tokens: list[str]) -> list[tuple[str, ...]]:
    return [tuple(tokens[i:i + NGRAM]) for i in range(len(tokens) - NGRAM + 1)]


def _listing_ngrams(listing: Listing) -> set[tuple[str, ...]]:
    return {g for run in _token_runs(listing) for g in _ngrams(run) if not STOPWORDS.issuperset(g)}


def _shared_phrases(listing: Listing, shared: set[tuple[str, ...]]) -> list[str]:
    """Merge overlapping shared 5-grams back into phrases (the listing's own words), keeping the long ones."""
    phrases: list[str] = []
    for tokens in _token_runs(listing):
        grams, i = _ngrams(tokens), 0
        while i < len(grams):
            if grams[i] in shared:
                j = i
                while j + 1 < len(grams) and grams[j + 1] in shared:
                    j += 1
                phrases.append(" ".join(tokens[i:j + NGRAM]))
                i = j + 1
            else:
                i += 1
    long_enough = [p for p in dict.fromkeys(phrases) if len(p.split()) >= MIN_PHRASE_WORDS]
    return sorted(long_enough, key=len, reverse=True)


class LinkedSellers:
    name = "deadlang-linked-sellers"
    capability = "linked_sellers"
    tier = "preferred"

    def __init__(self, market):
        self.market = market
        self._index_key: frozenset[str] | None = None
        self._ngram_sellers: dict[tuple[str, ...], set[str]] = {}
        self._hashes: dict[str, int] = {}                  # image rel path -> 64-bit perceptual hash

    def _load_hashes(self, rel_paths: set[str]) -> None:
        """Hash every image once; cached in data/phash_cache.json as {rel_path: [file_size, hex_hash]}."""
        import imagehash
        from PIL import Image

        cache_file: Path = self.market.image_path("phash_cache.json")
        try:
            cache = json.loads(cache_file.read_text())
        except (OSError, ValueError):
            cache = {}
        dirty = False
        for rel in sorted(rel_paths):
            path: Path = self.market.image_path(rel)
            try:
                size = path.stat().st_size
                if cache.get(rel, [None])[0] != size:
                    with Image.open(path) as img:
                        cache[rel] = [size, str(imagehash.phash(img))]
                    dirty = True
                self._hashes[rel] = int(cache[rel][1], 16)
            except OSError:
                continue                                   # missing or unreadable image: no photo evidence from it
        if dirty:
            try:
                tmp = cache_file.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(cache, sort_keys=True))
                tmp.replace(cache_file)
            except OSError:
                pass                                       # the cache is an optimisation only

    def _build_index(self, target: Listing, active: list[Listing]) -> None:
        ngram_sellers: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for l in active:
            for g in _listing_ngrams(l):
                ngram_sellers[g].add(l.seller_id)
        self._ngram_sellers = ngram_sellers
        self._load_hashes({p for l in [target, *active] for p in l.image_paths} - self._hashes.keys())

    async def run(self, call: SpecialistCall) -> SpecialistReply:
        try:
            target = await self.market.get_listing_snapshot(call.listing_id)   # works after removal too
        except KeyError:
            return SpecialistReply(ok=False, error=f"unknown listing {call.listing_id}")
        active = await self.market.all_active()
        key = frozenset(l.id for l in active)
        if key != self._index_key or any(p not in self._hashes for p in target.image_paths):
            await asyncio.to_thread(self._build_index, target, active)   # also picks up a revealed relist
            self._index_key = key

        rare = {g for g in _listing_ngrams(target)
                if len(self._ngram_sellers.get(g, set()) - {target.seller_id}) <= MAX_OTHER_SELLERS}
        target_photos = [(p, self._hashes[p]) for p in target.image_paths if p in self._hashes]

        by_seller: dict[str, dict] = {}
        for l in active:
            if l.seller_id == target.seller_id:
                continue
            shared = rare & _listing_ngrams(l)
            if len(_shared_phrases(target, shared)) < MIN_SHARED_PHRASES:
                shared = set()
            pairs = [[tp, p] for tp, th in target_photos for p in l.image_paths
                     if p in self._hashes and (th ^ self._hashes[p]).bit_count() <= MAX_PHOTO_DISTANCE]
            if not shared and not pairs:
                continue
            entry = by_seller.setdefault(l.seller_id, {"listing_ids": [], "ngrams": set(), "pairs": []})
            entry["listing_ids"].append(l.id)
            entry["ngrams"] |= shared
            entry["pairs"] += [p for p in pairs if p not in entry["pairs"]]

        linked = []
        for seller_id, entry in by_seller.items():
            phrases = _shared_phrases(target, entry["ngrams"])
            linked.append({
                "seller_id": seller_id, "seller_name": (await self.market.get_seller(seller_id)).name,
                "listing_ids": entry["listing_ids"],
                "shared_phrases": phrases[:3], "shared_phrase_count": len(phrases),
                "shared_photo_pairs": entry["pairs"], "shared_photo_count": len(entry["pairs"])})
        linked.sort(key=lambda e: (-(e["shared_phrase_count"] + e["shared_photo_count"]), e["seller_id"]))

        if not linked:
            summary = "No other sellers share rare phrasing or photos with this listing."
        else:
            names = ", ".join(f"{e['seller_name']} ({e['shared_phrase_count']} shared phrases, "
                              f"{e['shared_photo_count']} shared photos)" for e in linked[:5])
            more = f", and {len(linked) - 5} more" if len(linked) > 5 else ""
            noun = "seller shares" if len(linked) == 1 else "sellers share"
            summary = (f"{len(linked)} other {noun} rare phrasing or reused photos with this listing: "
                       f"{names}{more}.")
        data = {"listing_id": target.id, "linked": linked, "linked_seller_count": len(linked)}
        return SpecialistReply(ok=True, drafts=[EvidenceDraft(
            capability="linked_sellers", summary=summary, data=data, produced_by="code",
            specialist_name=self.name)])
