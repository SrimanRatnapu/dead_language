"""The UI fixture must stay valid against the frozen contract."""
from pathlib import Path

from deadlang.schemas import CaseFile, Evidence, Event, Listing, Seller, StancePost

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_case_events.jsonl"


def _events() -> list[Event]:
    return [Event.model_validate_json(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def test_every_event_and_payload_validates():
    events = _events()
    assert len(events) >= 12
    assert [e.seq for e in events] == list(range(len(events)))
    for e in events:
        p = e.payload
        if e.type == "case.started":
            Listing.model_validate(p["listing"]); Seller.model_validate(p["seller"])
        elif e.type == "evidence.added":
            Evidence.model_validate(p["evidence"])
        elif e.type == "stance.posted":
            StancePost.model_validate(p["post"])
        elif e.type == "case.ended":
            CaseFile.model_validate(p["case_file"])
        elif e.type == "round.started":
            assert isinstance(p["round"], int) and p["active"]


def test_story_shape():
    events = _events()
    assert events[0].type == "case.started" and events[-1].type == "case.ended"
    types = {e.type for e in events}
    assert {"specialist.selected", "claim.rejected", "round.started"} <= types


def test_selected_failed_and_rejected_payload_shapes():
    keys = {"specialist.selected": {"capability", "specialist_name", "why", "requested_by", "candidates"},
            "specialist.failed": {"capability", "specialist_name", "error", "fallback"},
            "claim.rejected": {"agent", "round", "claim_text", "reasons"},
            "listing.removed": {"listing_id", "relisted_as"}}
    seen = set()
    for e in _events():
        if e.type in keys:
            assert set(e.payload) == keys[e.type], e.type
            seen.add(e.type)
    assert {"specialist.selected", "claim.rejected"} <= seen
