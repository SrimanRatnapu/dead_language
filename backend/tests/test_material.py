import json
from pathlib import Path

import pytest

from deadlang import config, llm
from deadlang.evidence.board import numbers_from_text
from deadlang.llm import BudgetExceeded
from deadlang.schemas import SpecialistCall
from deadlang.specialists import material
from deadlang.specialists.base import Specialist
from deadlang.specialists.material import QuickExaminer, ThoroughExaminer
from tests.fakes import make_listing


class Market:
    def __init__(self, listing):
        self.listing = listing

    async def get_listing_snapshot(self, listing_id):
        return self.listing

    def image_path(self, rel):
        return Path("/data") / rel


class FakeVision:
    """Stands in for llm.call_vision_json; hands out scripted answers in call order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, **kw):
        self.calls.append(kw)
        out = self.answers.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def photo(index, mat, conf, features=("a visible feature",), region="base"):
    return {"index": index, "material": mat, "confidence": conf,
            "visible_features": list(features), "best_region": region}


def answer(*photos):
    return {"photos": list(photos)}


def second_look(*photos):
    """The thorough examiner's second look sees the photos in reverse order. Script it in terms of the
    original photos; this flips the indices to what the model would be shown."""
    n = len(photos)
    return answer(*[{**ph, "index": n - 1 - ph["index"]} for ph in reversed(photos)])


def setup(monkeypatch, *answers, images=("images/L0101_0.jpg", "images/L0101_1.jpg"), cls=ThoroughExaminer):
    fake = FakeVision(*answers)
    monkeypatch.setattr(llm, "call_vision_json", fake)
    listing = make_listing(image_paths=list(images), title="SECRET TITLE", description="SECRET DESCRIPTION",
                           price_usd=1450.0)
    return cls(Market(listing)), fake


def call(**params):
    return SpecialistCall(case_id="C-1", listing_id="L0101", capability="material_exam", params=params)


def data_numbers(obj):
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in data_numbers(v)]
    if isinstance(obj, list):
        return [n for v in obj for n in data_numbers(v)]
    if isinstance(obj, bool) or obj is None:
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return numbers_from_text(obj)
    return []


# ---------------- identity ----------------

def test_identities_match_the_contract():
    for cls, name, tier, model in [(ThoroughExaminer, "deadlang-examiner-thorough", "preferred", config.MODEL_STRONG),
                                   (QuickExaminer, "deadlang-examiner-quick", "fallback", config.MODEL_FAST)]:
        ex = cls(Market(make_listing()))
        assert (ex.name, ex.capability, ex.tier, ex.model) == (name, "material_exam", tier, model)
        assert isinstance(ex, Specialist)


# ---------------- thorough ----------------

async def test_thorough_agreement_reports_material_with_min_confidence(monkeypatch):
    run1 = answer(photo(0, "elephant_ivory", 0.9, ["cross-hatched lines on the base"]),
                  photo(1, "cannot_tell", 0.2))
    run2 = second_look(photo(0, "elephant_ivory", 0.8, ["fine even grain"]), photo(1, "bone", 0.7))
    ex, fake = setup(monkeypatch, run1, run2)

    reply = await ex.run(call())

    assert reply.ok and len(reply.drafts) == 1
    d = reply.drafts[0]
    assert (d.capability, d.produced_by, d.specialist_name) == ("material_exam", "model", "deadlang-examiner-thorough")
    assert d.confidence == 0.8
    p0, p1 = d.data["photos"]
    assert (p0["index"], p0["material"], p0["confidence"]) == (0, "elephant_ivory", 0.8)
    assert (p1["index"], p1["material"], p1["confidence"]) == (1, "cannot_tell", 0.0)   # runs disagreed
    assert d.data["overall"] == "elephant_ivory"
    assert d.data["mode"] == "thorough" and d.data["model"] == config.MODEL_STRONG
    assert d.summary == ("Photo 0 shows cross-hatched lines on the base consistent with elephant ivory "
                         "(confidence 0.8); 1 other photo: cannot tell.")
    assert len(fake.calls) == 2                                    # two independent runs
    assert all(c["model"] == config.MODEL_STRONG and c["case_id"] == "C-1" for c in fake.calls)
    assert all(len(c["image_paths"]) == 2 for c in fake.calls)


async def test_thorough_disagreement_everywhere_is_cannot_tell(monkeypatch):
    run1 = answer(photo(0, "elephant_ivory", 0.9, ["f1"]), photo(1, "wood", 0.6, ["f2"]))
    run2 = second_look(photo(0, "bone", 0.7, ["f3"]), photo(1, "cannot_tell", 0.3, ["f4"]))
    ex, _ = setup(monkeypatch, run1, run2)

    d = (await ex.run(call())).drafts[0]

    assert [p["material"] for p in d.data["photos"]] == ["cannot_tell", "cannot_tell"]
    assert d.confidence == 0.0 and d.data["overall"] == "cannot_tell"
    assert d.data["photos"][0]["visible_features"] == ["f1", "f3"]    # features from both runs, max 3
    assert d.summary == ("The examiner could not tell the material from the 2 photos "
                         "(thorough mode: the two runs disagreed or both were unsure).")


async def test_thorough_both_runs_cannot_tell(monkeypatch):
    a = answer(photo(0, "cannot_tell", 0.5), photo(1, "cannot_tell", 0.4))
    ex, _ = setup(monkeypatch, a, a)
    d = (await ex.run(call())).drafts[0]
    assert d.confidence == 0.0 and d.data["overall"] == "cannot_tell"


# ---------------- quick ----------------

async def test_quick_runs_once_and_caps_confidence(monkeypatch):
    ex, fake = setup(monkeypatch, answer(photo(0, "bone", 0.95, ["small dark pits"]), photo(1, "bone", 0.55)),
                     cls=QuickExaminer)

    d = (await ex.run(call())).drafts[0]

    assert len(fake.calls) == 1 and fake.calls[0]["model"] == config.MODEL_FAST
    assert [p["confidence"] for p in d.data["photos"]] == [0.6, 0.6]    # 0.95 capped; 0.55 prints as 0.6
    assert d.confidence == 0.6 and d.data["mode"] == "quick" and d.specialist_name == "deadlang-examiner-quick"
    assert d.summary.startswith("Photo 0 shows small dark pits consistent with bone (confidence 0.6)")


async def test_quick_none_decisive_wording(monkeypatch):
    ex, _ = setup(monkeypatch, answer(photo(0, "cannot_tell", 0.3), photo(1, "cannot_tell", 0.2)),
                  cls=QuickExaminer)
    d = (await ex.run(call())).drafts[0]
    assert d.summary == ("The examiner could not tell the material from the 2 photos "
                         "(quick mode: the single run was unsure).")


# ---------------- which photos ----------------

async def test_image_index_limits_to_one_photo_and_keeps_its_number(monkeypatch):
    images = ("images/L0101_0.jpg", "images/L0101_1.jpg", "images/L0101_2.jpg")
    ex, fake = setup(monkeypatch, answer(photo(0, "wood", 0.8, ["wood grain rings"])),
                     answer(photo(0, "wood", 0.7, ["brown grain"])), images=images)

    d = (await ex.run(call(image_index=2))).drafts[0]

    for c in fake.calls:
        assert c["image_paths"] == [Path("/data/images/L0101_2.jpg")]
    assert [p["index"] for p in d.data["photos"]] == [2]
    assert d.summary == "Photo 2 shows wood grain rings consistent with wood (confidence 0.7)."


async def test_at_most_three_photos_are_examined(monkeypatch):
    images = tuple(f"images/L0101_{i}.jpg" for i in range(5))
    a = answer(*[photo(i, "wood", 0.8) for i in range(3)])
    ex, fake = setup(monkeypatch, a, a, images=images)
    d = (await ex.run(call())).drafts[0]
    assert len(fake.calls[0]["image_paths"]) == 3 and len(d.data["photos"]) == 3


async def test_no_images_is_an_error_and_makes_no_model_call(monkeypatch):
    ex, fake = setup(monkeypatch, images=())
    reply = await ex.run(call())
    assert (reply.ok, reply.error, reply.drafts) == (False, "no_images", [])
    assert fake.calls == []


async def test_image_index_out_of_range_is_an_error(monkeypatch):
    ex, fake = setup(monkeypatch)
    reply = await ex.run(call(image_index=7))
    assert not reply.ok and reply.error == "image_index_out_of_range"
    assert fake.calls == []


# ---------------- robustness ----------------

async def test_budget_exceeded_becomes_budget_error(monkeypatch):
    ex, _ = setup(monkeypatch, BudgetExceeded("cap"))
    reply = await ex.run(call())
    assert (reply.ok, reply.error) == (False, "budget")


async def test_malformed_model_output_is_normalised(monkeypatch):
    messy = answer(photo(0, "ivory", 1.7, ["a", "b", "c", "d"]))        # unknown material, confidence > 1
    ex, _ = setup(monkeypatch, messy, images=("images/L0101_0.jpg", "images/L0101_1.jpg"), cls=QuickExaminer)
    d = (await ex.run(call())).drafts[0]
    p0, p1 = d.data["photos"]
    assert p0["material"] == "cannot_tell" and p0["confidence"] == 0.0
    assert p1 == {"index": 1, "material": "cannot_tell", "confidence": 0.0, "visible_features": [], "best_region": ""}


async def test_model_only_sees_photos_never_listing_text(monkeypatch):
    ex, fake = setup(monkeypatch, answer(photo(0, "bone", 0.5), photo(1, "bone", 0.5)), cls=QuickExaminer)
    await ex.run(call())
    sent = json.dumps({k: str(v) for k, v in fake.calls[0].items()})
    for secret in ("SECRET TITLE", "SECRET DESCRIPTION", "1450"):
        assert secret not in sent
    assert fake.calls[0]["user"] == ("Photos are numbered in the order given, starting at 0. "
                                     "Return one entry per photo.")
    assert fake.calls[0]["schema_name"] == "report_material"
    assert "Schreger" in fake.calls[0]["system"]


async def test_every_number_in_the_summary_is_stored_in_data(monkeypatch):
    run1 = answer(photo(0, "elephant_ivory", 0.87, ["lines"]), photo(1, "cannot_tell", 0.2))
    run2 = second_look(photo(0, "elephant_ivory", 0.93, ["lines"]), photo(1, "bone", 0.9))
    ex, _ = setup(monkeypatch, run1, run2)
    d = (await ex.run(call())).drafts[0]
    stored = set(data_numbers(d.data))
    assert set(numbers_from_text(d.summary)) <= stored
    assert d.data["photos"][0]["confidence"] == 0.9        # min(0.87, 0.93) = 0.87, rounded to 1 decimal


# ---------------- per-image method for the accuracy test ----------------

async def test_examine_returns_per_photo_results_for_the_eval(monkeypatch):
    ex, fake = setup(monkeypatch, answer(photo(0, "bone", 0.7, ["pits"])), cls=QuickExaminer)
    results = await ex.examine([Path("/data/museum/1.jpg")], case_id="examiner_eval")
    assert [(r["index"], r["material"], r["confidence"]) for r in results] == [(0, "bone", 0.6)]
    assert fake.calls[0]["case_id"] == "examiner_eval"


def test_module_exposes_the_two_examiners():
    assert material.ThoroughExaminer is ThoroughExaminer and material.QuickExaminer is QuickExaminer


# ---------------- demo hardening: the thorough examiner's two looks really differ ----------------

async def test_the_second_look_sees_the_photos_reversed_with_a_bases_first_note(monkeypatch):
    images = tuple(f"images/L0101_{i}.jpg" for i in range(3))
    same = answer(*[photo(i, "wood", 0.8) for i in range(3)])
    ex, fake = setup(monkeypatch, same, same, images=images)

    await ex.run(call())

    first, second = fake.calls
    assert first["image_paths"] == [Path("/data") / f"images/L0101_{i}.jpg" for i in (0, 1, 2)]
    assert second["image_paths"] == list(reversed(first["image_paths"]))
    assert first["user"] == material.USER_MESSAGE
    assert second["user"] == material.USER_MESSAGE + " Examine bases and cut surfaces first."
    assert first["system"] == second["system"] and first["schema"] == second["schema"]


async def test_photo_numbers_stay_correct_when_the_second_look_is_reversed(monkeypatch):
    images = tuple(f"images/L0101_{i}.jpg" for i in range(3))
    run1 = answer(photo(0, "elephant_ivory", 0.9, ["lines"]), photo(1, "bone", 0.8, ["pits"]),
                  photo(2, "wood", 0.7, ["grain"]))
    # in original-photo terms the second look agrees on photos 0 and 2 but sees wood in photo 1
    run2 = second_look(photo(0, "elephant_ivory", 0.84, ["lines"]), photo(1, "wood", 0.6, ["rings"]),
                       photo(2, "wood", 0.75, ["grain"]))
    ex, _ = setup(monkeypatch, run1, run2, images=images)

    d = (await ex.run(call())).drafts[0]

    by_index = {p["index"]: p for p in d.data["photos"]}
    assert by_index[0]["material"] == "elephant_ivory" and by_index[0]["confidence"] == 0.8   # min(0.9, 0.84) = 0.84 -> 0.8
    assert by_index[1]["material"] == "cannot_tell"                                          # the looks disagreed on photo 1 only
    assert by_index[2]["material"] == "wood" and by_index[2]["confidence"] == 0.7
    assert [p["index"] for p in d.data["photos"]] == [0, 1, 2]
    assert d.data["photos"][1]["visible_features"] == ["pits", "rings"]       # features from the right photo in each look


async def test_a_single_photo_still_gets_the_different_instruction_for_its_second_look(monkeypatch):
    a = answer(photo(0, "bone", 0.7))
    ex, fake = setup(monkeypatch, a, a)
    await ex.run(call(image_index=1))
    assert fake.calls[0]["image_paths"] == fake.calls[1]["image_paths"] == [Path("/data/images/L0101_1.jpg")]
    assert fake.calls[1]["user"].endswith("Examine bases and cut surfaces first.")
    assert fake.calls[0]["user"] == material.USER_MESSAGE


async def test_the_quick_examiner_is_unchanged(monkeypatch):
    ex, fake = setup(monkeypatch, answer(photo(0, "bone", 0.5), photo(1, "bone", 0.5)), cls=QuickExaminer)
    await ex.run(call())
    assert len(fake.calls) == 1 and fake.calls[0]["user"] == material.USER_MESSAGE
    assert fake.calls[0]["image_paths"] == [Path("/data/images/L0101_0.jpg"), Path("/data/images/L0101_1.jpg")]


# ---------------- diagnostics: examine(detail=True) shows each look; the default output is unchanged ----------------

async def test_examine_detail_shows_each_look_and_default_output_is_unchanged(monkeypatch):
    run1 = answer(photo(0, "elephant_ivory", 0.9, ["lines"]), photo(1, "bone", 0.8, ["pits"]))
    run2 = second_look(photo(0, "elephant_ivory", 0.84, ["lines"]), photo(1, "wood", 0.6, ["rings"]))
    ex, _ = setup(monkeypatch, run1, run2)
    paths = [Path("/data/a.jpg"), Path("/data/b.jpg")]

    detailed = await ex.examine(paths, case_id="x", detail=True)

    assert [[look["material"] for look in p["looks"]] for p in detailed] == [["elephant_ivory", "elephant_ivory"], ["bone", "wood"]]
    assert detailed[0]["looks"][1]["confidence"] == 0.8                 # 0.84 shown to one decimal, like the rest
    assert detailed[1]["material"] == "cannot_tell"

    ex2, _ = setup(monkeypatch, run1, second_look(photo(0, "elephant_ivory", 0.84, ["lines"]), photo(1, "wood", 0.6, ["rings"])))
    plain = await ex2.examine(paths, case_id="x")
    assert all("looks" not in p for p in plain)                         # evidence data stays exactly as before


async def test_the_evidence_a_case_sees_has_no_looks_field(monkeypatch):
    a = answer(photo(0, "bone", 0.7), photo(1, "bone", 0.7))
    ex, _ = setup(monkeypatch, a, second_look(photo(0, "bone", 0.7), photo(1, "bone", 0.7)))
    d = (await ex.run(call())).drafts[0]
    assert all("looks" not in p for p in d.data["photos"])
