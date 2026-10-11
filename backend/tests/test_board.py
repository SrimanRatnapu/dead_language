from deadlang.evidence.board import EvidenceBoard
from deadlang.schemas import EvidenceDraft


def draft(cap, summary, data, **kw):
    return EvidenceDraft(capability=cap, summary=summary, data=data, produced_by="code", specialist_name="x", **kw)


def make_board():
    b = EvidenceBoard("C-1")
    b.add(draft("listing_snapshot", 'Listing L1 "Old bone netsuke" for $1,450.', {"price_usd": 1450.0}), "intake")
    b.add(draft("price_check", "Median $95; this listing is 15.3x that.", {"median_usd": 95, "n": 38}), "intake")
    b.add(draft("linked_sellers", "Two sellers share a phrase.",
                {"shared_phrases": ["Ships discreetly from our family collection"], "nested": {"deep": ["Rare Phrase", 7.5]}},
                confidence=0.8), "case_officer")
    return b


def test_ids_are_sequential_and_lookup_works():
    b = make_board()
    assert [e.id for e in b.all()] == ["E0", "E1", "E2"]
    assert b.ids() == {"E0", "E1", "E2"} and b.count() == 3
    assert b.get("E1").requested_by == "intake" and b.get("E9") is None
    assert [e.id for e in b.added_since(1)] == ["E1", "E2"]
    assert b.added_since(3) == []


def test_numbers_in_summary_data_and_comma_strings():
    b = make_board()
    assert 1450.0 in b.numbers_in(["E0"])          # from "$1,450" and from data
    nums = b.numbers_in(["E1"])
    assert 15.3 in nums and 95.0 in nums and 38.0 in nums
    assert 7.5 in b.numbers_in(["E2"])
    assert 15.3 not in b.numbers_in(["E0"])        # only cited items are searched


def test_text_in_finds_nested_strings_lowercased():
    b = make_board()
    t = b.text_in(["E2"])
    assert "ships discreetly from our family collection" in t and "rare phrase" in t
    assert "old bone netsuke" not in t


def test_render_contains_ids_and_confidence():
    b = make_board()
    out = b.render_for_prompt()
    assert out.startswith("E0 · listing_snapshot · by x (code) · requested by intake")
    assert "E2 · linked_sellers" in out and "Model confidence: 0.8" in out
    assert "  Summary: Median $95; this listing is 15.3x that." in out


def test_dict_keys_never_ground_numbers():
    b = EvidenceBoard("C-1")
    b.add(draft("price_check", "nothing numeric", {"1000": "unrelated", "n": 4}), "intake")
    assert b.numbers_in(["E0"]) == [4.0]


def test_render_truncates_long_data_to_1200_chars():
    from deadlang.evidence.board import render_evidence
    b = EvidenceBoard("C-1")
    b.add(draft("price_check", "s", {"blob": "a" * 5000}), "intake")
    line = next(l for l in render_evidence(b.all()).splitlines() if l.startswith("  Data:"))
    assert len(line) <= len("  Data: ") + 1201 and line.endswith("…")
