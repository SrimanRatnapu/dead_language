"""Record SCRIPTED walkthroughs of the four demo cases for the UI (no model calls, no API key).

Run from the repo root:  uv run --project backend python scripts/record_scripted_demo.py

Everything runs through the real local stack (Facilitator, claim validator, stop/outcome rules, discovery,
transport, the real code specialists on the real dataset). Only the Anthropic client is replaced: the three
agents' posts and the material examiner's readings below are written by hand. Replace these files with
recorded live runs when they exist; the UI labels them as scripted until then.

Writes fixtures/replays/<name>.jsonl and copies them to frontend/public/replays/ (+ index.json).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from deadlang import config, llm  # noqa: E402
from deadlang.agntcy import discovery as discovery_mod, transport as transport_mod  # noqa: E402
from deadlang.api.events import EventBus  # noqa: E402
from deadlang.deliberation.facilitator import Facilitator  # noqa: E402
import deadlang.marketplace.client as market_mod  # noqa: E402
from deadlang.marketplace.store import MarketplaceStore  # noqa: E402

DATA = ROOT / "data"
DEMO = json.loads((DATA / "demo_cases.json").read_text())
PAUSE_S = {"case.started": 0.0, "evidence.added": 0.9, "specialist.selected": 0.5, "specialist.failed": 0.8,
           "round.started": 1.6, "stance.posted": 2.4, "claim.rejected": 1.0, "listing.removed": 1.2,
           "case.ended": 2.0}

IVORY = {"material": "elephant_ivory", "confidence": 0.8, "best_region": "flat back of the carving",
         "visible_features": ["cross-hatched grain lines on the back", "warm, slightly translucent surface"]}
UNSURE = {"material": "cannot_tell", "confidence": 0.0, "visible_features": [], "best_region": ""}


def tagua(confidence: float, feature: str) -> dict:
    return {"material": "tagua_nut", "confidence": confidence, "best_region": "edge of the carving",
            "visible_features": [feature, "very fine, faint concentric grain"]}


def post(stance, confidence, claims, *, rebut=None, requests=(), challenge=None, changed=None, ready=False):
    out = {"stance": stance, "confidence": confidence, "ready_to_close": ready,
           "claims": [{"text": t, "evidence_ids": ids} for t, ids in claims],
           "requests": [{"capability": c, "question": q, "reason": r, "params": p} for c, q, r, p in requests]}
    if rebut:
        out["rebuttal"] = dict(zip(("target_agent", "target_claim", "response", "evidence_ids"), rebut))
    if challenge:
        out["challenge"] = {"target_agent": challenge[0], "question": challenge[1]}
    if changed:
        out["changed_because"], out["changed_because_evidence"] = changed
    return out


# Evidence is cited by role, resolved to real ids from the board each agent is shown:
#   @E0 listing · @price · @inv / @inv2 (first / latest seller inventory) · @linked / @linked2 ·
#   @cites / @law (the two legal items) · @exam / @exam2 (first / latest photo exam) · @notice / @notice2
def d1(f: dict, linked_photo_seller: str) -> dict:
    price = f"At {f['price']} this piece is priced {f['ratio']}x the {f['median']} median for comparable bone netsuke."
    unsure = "The examiner could not tell the material from any of the 3 photos, so nothing on the board shows this is not bone."
    return {"exam": {3: [UNSURE, UNSURE, UNSURE], 1: [IVORY]}, "posts": {
        "buyer": [
            post("file", 0.75, [
                (price, ["@price"]),
                ('The seller writes "Priced for buyers who know what they are looking at" and stresses weight and '
                 '"very fine close grain", details a bone buyer would not pay extra for.', ["@E0"]),
                ("The same photo also appears under a second seller account.", ["@linked"])]),
            post("file", 0.9, [
                ("The close exam of photo 1 found cross-hatched grain consistent with elephant ivory.", ["@exam2"]),
                (price, ["@price"])],
                rebut=("defender", unsure, "The closer exam you asked for now reports ivory grain on the back.", ["@exam2"]),
                ready=True)],
        "defender": [
            post("dismiss", 0.6, [
                (unsure, ["@exam"]),
                (f"Bone netsuke often sell for {f['unsupported']} or more when they are old and signed.", ["@price"])],
                requests=[("material_exam", "Look closely at the back of the piece in photo 1: bone pitting, or grain?",
                           "A close look at the back could clear the seller.", {"image_index": 1})]),
            post("file", 0.7, [
                ("Photo 1 shows cross-hatched grain consistent with elephant ivory, so the bone description no longer holds.", ["@exam2"]),
                ("I have no innocent explanation for one photo appearing under two seller accounts.", ["@linked"])],
                rebut=("buyer", price, "I argued an optimistic seller could explain the price. With the exam result "
                       "that explanation is no longer plausible.", ["@exam2"]),
                changed=("The close exam I asked for reports cross-hatched grain on photo 1, which bone does not have, "
                         f"and the price is {f['ratio']}x the bone median.", ["@exam2", "@price"]),
                ready=True)],
        "caseload": [
            post("need_more", 0.5, [
                ("The item ships from California, where selling ivory is unlawful under Fish and Game Code section 2022.", ["@law"]),
                ("Two other sellers share wording with this listing and one of them reuses a photo, but this seller "
                 f"has only {f['listings']} listings.", ["@linked", "@inv"])],
                requests=[("seller_inventory", "What else does the seller who reuses this photo have listed?",
                           "A pattern across accounts is worth an investigator's time; a single item is not.",
                           {"seller_id": linked_photo_seller})],
                challenge=("defender", "What innocent explanation covers the same photo appearing under two different seller accounts?")),
            post("file", 0.8, [
                ("This listing is linked to 2 other sellers by shared wording, and one of them reuses its photo.", ["@linked"]),
                ("The account that reuses the photo also lists carvings described as bone.", ["@inv2"]),
                ("The sale is unlawful where the item ships from.", ["@law"])],
                rebut=("defender", unsure, "Several accounts selling the same piece are worth an investigator's hours "
                       "whatever the first exam said.", ["@linked"]),
                changed=("The accounts connect into a pattern: shared wording across all of them and a reused photo.",
                         ["@linked", "@inv2"]),
                ready=True)]}}


def d2(f: dict) -> dict:
    hk = "The listing says the piece was sold in Hong Kong, a market where carvings of many materials change hands."
    seed = "The examiner sees brown seed skin consistent with tagua nut in the photos."
    return {"exam": {3: [tagua(0.7, "brown seed husk left around the carving"), UNSURE,
                         tagua(0.8, "patch of brown seed skin")],
                     1: [tagua(0.9, "brown seed skin at the edge of the carving")]}, "posts": {
        "buyer": [
            post("need_more", 0.4, [
                (hk, ["@E0"]),
                ("The examiner could not tell the material in one of the 3 photos.", ["@exam"])],
                requests=[("material_exam", "Is the cream surface in photo 1 nut or tooth?",
                           "One photo is still open; a close look settles it either way.", {"image_index": 1})]),
            post("dismiss", 0.8, [
                ("Photo 1 shows brown seed skin consistent with tagua nut, and the price fits tagua.", ["@exam2", "@price"])],
                rebut=("defender", seed, "I asked for a closer look at the one photo left open. It agrees with you.", ["@exam2"]),
                changed=("The close exam of photo 1 shows seed skin and nut grain.", ["@exam2"]), ready=True)],
        "defender": [
            post("dismiss", 0.85, [
                (seed, ["@exam"]),
                (f"At {f['price']} the price is {f['ratio']}x the {f['median']} median for tagua figurines, so nobody is paying an ivory price.", ["@price"])]),
            post("dismiss", 0.9, [
                ("Every photo with a readable surface shows tagua nut.", ["@exam", "@exam2"]),
                (f"At {f['price']} the price is {f['ratio']}x the {f['median']} median for tagua figurines.", ["@price"])],
                rebut=("buyer", hk, "Where a carving was sold says nothing about what it is made of. The photos do.", ["@exam2"]),
                ready=True)],
        "caseload": [
            post("dismiss", 0.8, [
                (f"One {f['price']} item from a seller whose {f['listings']} listings total {f['total']} is not worth an investigator's time.", ["@inv", "@price"]),
                ("No other sellers share wording or photos with this listing.", ["@linked"])]),
            post("dismiss", 0.85, [
                ("The item is a tagua nut carving, which is legal to sell.", ["@exam2"]),
                ("No other sellers share wording or photos with this listing.", ["@linked"])],
                rebut=("buyer", hk, "A place of sale is not a pattern. There is one cheap item and no linked sellers.", ["@linked"]),
                ready=True)]}}


def d3(f: dict) -> dict:
    price = f"At {f['price']} the piece is priced {f['ratio']}x the {f['median']} median for comparable bone netsuke."
    unsure = "The examiner could not tell the material from the 3 photos."
    return {"remove_at_first_post": True, "exam": {3: [UNSURE, UNSURE, UNSURE], 1: [IVORY]}, "posts": {
        "buyer": [
            post("file", 0.8, [
                (price, ["@price"]),
                ('The seller asks buyers to "study the picture of the back" and sells to "serious collectors only".', ["@E0"])]),
            post("file", 0.9, [
                ("After the listing was removed, a new listing reusing its photo appeared under another account.", ["@linked2", "@notice2"]),
                (price, ["@price"])],
                rebut=("defender", unsure, "The close exam of photo 1 now reports ivory grain.", ["@exam2"]), ready=True)],
        "defender": [
            post("need_more", 0.5, [(unsure, ["@exam"])],
                 requests=[("material_exam", "Look closely at the back of the piece in photo 1.",
                            "The seller points buyers at the back; a close look could clear them.", {"image_index": 1})]),
            post("file", 0.7, [
                ("A seller removing a listing is not, by itself, evidence that the item is illegal.", ["@notice"]),
                ("Photo 1 shows cross-hatched grain consistent with elephant ivory.", ["@exam2"]),
                ("The relisted copy reuses this listing's photo under a different seller account.", ["@linked2"])],
                rebut=("buyer", price, "Price alone could be an optimistic seller. Price plus ivory grain plus a "
                       "relist under a new account cannot.", ["@exam2", "@linked2"]),
                changed=("Removal alone proves nothing, but the close exam reports ivory grain and the same photo was "
                         "relisted under a new account.", ["@exam2", "@linked2"]),
                ready=True)],
        "caseload": [
            post("need_more", 0.55, [
                ("Two other sellers share wording with this listing.", ["@linked"]),
                ("The item ships from California, where selling ivory is unlawful under Fish and Game Code section 2022.", ["@law"])],
                requests=[("linked_sellers", "Re-check which accounts share wording or photos with this listing.",
                           "Whether this is one item or a pattern decides if it is worth filing.", {})]),
            post("file", 0.85, [
                ("3 other sellers now share wording or photos with this listing, one through a reused photo.", ["@linked2"]),
                ("The sale is unlawful where the item ships from.", ["@law"])],
                rebut=("defender", unsure, "Whatever the first exam said, the accounts are now a pattern: the listing "
                       "came back under a new seller.", ["@linked2"]),
                changed=("The linked accounts grew after the removal and include a relist with the same photo.", ["@linked2", "@notice2"]),
                ready=True)]}}


def d4(f: dict) -> dict:
    price = f"At {f['price']} the figure is priced {f['ratio']}x the {f['median']} median for comparable bone figurines."
    unsure = "The examiner could not tell the material from the single photo."
    return {"exam": {1: [UNSURE]}, "posts": {
        "buyer": [
            post("file", 0.6, [
                (price, ["@price"]),
                ('The seller says it "feels heavy for how small it is" and priced it from an auction house result.', ["@E0"])],
                challenge=("defender", "What bone figure of this size sells for this price?")),
            post("file", 0.6, [
                (price, ["@price"]),
                ("Apart from price, the board holds no material finding in either direction.", ["@exam2"])],
                rebut=("defender", unsure, "Unable to tell is not a finding of bone. The price still has no innocent "
                       "comparison on the board.", ["@price"]), ready=True)],
        "defender": [
            post("dismiss", 0.55, [
                (unsure, ["@exam"]),
                ('The seller says "I am no expert" and "I was told it is old bone", which fits an estate seller '
                 "guessing at a price.", ["@E0"])],
                challenge=("buyer", "Which fact on the board, other than price, points to ivory?")),
            post("dismiss", 0.55, [
                ("Two examinations of the only photo could not tell the material.", ["@exam", "@exam2"]),
                ('The seller says "I am no expert", which fits a guessed price.', ["@E0"])],
                rebut=("buyer", price, "A high asking price from a seller who admits guessing is not evidence of "
                       "what the figure is made of.", ["@E0"]), ready=True)],
        "caseload": [
            post("need_more", 0.6, [
                ("This seller has 1 listing, and no other sellers share its wording or photos.", ["@inv", "@linked"]),
                (f"One item worth {f['total']} is a weak use of investigator time without a material finding.", ["@inv"])],
                requests=[("material_exam", "Can a second close look at the only photo settle the material?",
                           "Without a material finding this is one item and one price.", {"image_index": 0})]),
            post("need_more", 0.6, [
                ("A second look at the photo still could not tell the material.", ["@exam2"]),
                ("This seller has 1 listing, and no other sellers share its wording or photos.", ["@inv", "@linked"])],
                rebut=("buyer", price, "The price is unusual, but one item with no material finding and no linked "
                       "sellers is for a person to weigh, not for me to file.", ["@inv", "@linked"]), ready=True)]}}


class ScriptedAnthropic:
    """Stands in for the Anthropic client: answers each tool call from the script."""

    def __init__(self, script: dict, on_first_post):
        self.messages = self
        self.script = script
        self.turn = {agent: 0 for agent in script["posts"]}
        self.on_first_post = on_first_post

    @staticmethod
    def _refs(board_text: str) -> dict[str, str]:
        ids: dict[str, list[str]] = {}
        for evidence_id, capability in re.findall(r"^(E\d+) · (\w+) ·", board_text, flags=re.M):
            ids.setdefault(capability, []).append(evidence_id)
        first, last = (lambda c: ids[c][0]), (lambda c: ids[c][-1])
        table = {"@E0": lambda: "E0", "@price": lambda: first("price_check"),
                 "@inv": lambda: first("seller_inventory"), "@inv2": lambda: last("seller_inventory"),
                 "@linked": lambda: first("linked_sellers"), "@linked2": lambda: last("linked_sellers"),
                 "@cites": lambda: ids["legal_lookup"][0], "@law": lambda: ids["legal_lookup"][1],
                 "@exam": lambda: first("material_exam"), "@exam2": lambda: last("material_exam"),
                 "@notice": lambda: first("system_notice"), "@notice2": lambda: last("system_notice")}
        return {ref: get() for ref, get in table.items() if _safe(get)}

    async def create(self, **req):
        name = req["tools"][0]["name"]
        content = req["messages"][0]["content"]
        if name == "report_material":
            images = sum(1 for block in content if block.get("type") == "image")
            out = {"photos": [{"index": i, **photo} for i, photo in enumerate(self.script["exam"][images])]}
        elif name == "post_position":
            if self.on_first_post:
                hook, self.on_first_post = self.on_first_post, None
                await hook()
            system = req["system"] if isinstance(req["system"], str) else json.dumps(req["system"])
            agent = next(a for a in ("buyer", "defender", "caseload")
                         if f"You are {'the ' + a.capitalize() if a != 'caseload' else 'Caseload'}" in system)
            repair = "# Fix these problems" in content
            if not repair:
                self.turn[agent] += 1
            out = json.loads(json.dumps(self.script["posts"][agent][self.turn[agent] - 1]))
            refs = self._refs(content)
            out = json.loads(re.sub(r"@\w+", lambda m: refs[m.group()], json.dumps(out)))
        else:
            raise RuntimeError(f"unscripted tool call: {name}")
        return NS(content=[NS(type="tool_use", name=name, input=out)], usage=NS(input_tokens=0, output_tokens=0))


def _safe(get) -> bool:
    try:
        get()
        return True
    except (KeyError, IndexError):
        return False


async def record(name: str, listing_id: str, script: dict, market) -> list[dict]:
    await market.reset_demo()
    bus = EventBus(runs_dir=None)
    facilitator = Facilitator(market, transport_mod.get_transport(), discovery_mod.get_discovery(), bus)

    async def remove():
        relisted = await market.remove_listing(listing_id)
        await facilitator.notify_listing_removed(listing_id, relisted)

    llm.set_client_for_tests(ScriptedAnthropic(script, remove if script.get("remove_at_first_post") else None))
    case_id = f"DEMO-{name.split('_')[0].upper()}"
    outcome = await facilitator.run_case(case_id, listing_id)
    await market.reset_demo()

    events = [e.model_dump(mode="json") for e in bus.history(case_id)]
    clock = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)
    stamped: dict[str, dict] = {}
    for e in events:                       # the run takes milliseconds; give the replay a watchable pace
        clock += timedelta(seconds=PAUSE_S.get(e["type"], 1.0))
        e["at"] = clock.isoformat()
        if e["type"] == "evidence.added":      # same synthetic clock inside the evidence, so re-runs are identical
            ev = e["payload"]["evidence"]
            ev["created_at"] = e["at"]
            ev["summary"] = re.sub(r"\bat \d\d:\d\d;", f"at {clock:%H:%M};", ev["summary"])
            if ev["capability"] == "material_exam":
                ev["data"]["model"] = "scripted reading (no model call)"
            stamped[ev["id"]] = ev
    case_file = events[-1]["payload"]["case_file"]
    case_file["evidence"] = [stamped[ev["id"]] for ev in case_file["evidence"]]
    case_file["created_at"] = events[-1]["at"]
    rejected = [e["payload"]["claim_text"] for e in events if e["type"] == "claim.rejected"]
    rounds = sum(e["type"] == "round.started" for e in events)
    print(f"{name:14} {listing_id}  {outcome.outcome:9} stop={outcome.stop_reason:14} rounds={rounds} "
          f"evidence={len(outcome.evidence)} events={len(events)} rejected={rejected}")
    return events


async def main() -> None:
    config.USAGE_FILE = Path(tempfile.mkdtemp()) / "usage.json"
    market = market_mod.LocalMarketplaceClient(MarketplaceStore.from_dir(DATA), DATA)
    market_mod._client = market
    await discovery_mod.get_discovery().register_all()

    # Ask through the transport so the pipeline's own linked-sellers specialist builds its index now;
    # built lazily mid-case (in a thread) it would make the order of intake evidence vary between runs.
    from deadlang.schemas import SpecialistCall
    links = (await transport_mod.get_transport().call_specialist("deadlang-linked-sellers", SpecialistCall(
        case_id="setup", listing_id=DEMO["d1_network"], capability="linked_sellers"))).drafts[0].data["linked"]
    photo_seller = next(e["seller_id"] for e in links if e["shared_photo_count"])

    async def facts(listing_id: str) -> dict:
        """The numbers the scripted claims quote, read from the real specialists so they always match the board."""
        async def data(name, capability):
            call = SpecialistCall(case_id="setup", listing_id=listing_id, capability=capability)
            return (await transport_mod.get_transport().call_specialist(name, call)).drafts[0].data
        price, inv = await data("deadlang-price-checker", "price_check"), await data("deadlang-seller-inventory", "seller_inventory")
        return {"price": f"${price['price_usd']:,}", "ratio": price["ratio"], "median": f"${price['median_usd']:,}",
                "unsupported": f"${round(price['price_usd'] * 0.6, -2):,.0f}",      # in no evidence: gets rejected
                "listings": inv["listing_count"], "total": f"${inv['total_value_usd']:,}"}

    f = {name: await facts(listing_id) for name, listing_id in DEMO.items()}
    cases = {"d1_network": d1(f["d1_network"], photo_seller), "d2_tagua": d2(f["d2_tagua"]),
             "d3_removed": d3(f["d3_removed"]), "d4_ambiguous": d4(f["d4_ambiguous"])}
    public = ROOT / "frontend" / "public" / "replays"
    for name, script in cases.items():
        events = await record(name, DEMO[name], script, market)
        text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
        (ROOT / "fixtures" / "replays" / f"{name}.jsonl").write_text(text)
        (public / f"{name}.jsonl").write_text(text)
    (public / "index.json").write_text(json.dumps(list(cases)) + "\n")
    llm.set_client_for_tests(None)


if __name__ == "__main__":
    asyncio.run(main())
