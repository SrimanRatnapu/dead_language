import pytest

from deadlang import config, llm
from deadlang.evidence.board import numbers_from_text
from deadlang.llm import BudgetExceeded
from deadlang.schemas import SpecialistCall
from deadlang.specialists.base import Specialist
from deadlang.specialists.language import Translator
from tests.fakes import make_listing

TRANSLATION = {
    "title_en": "Old carved figurine, ivory colored, family collection",
    "description_en": "Carved by hand, about 60 years old. Message me on Zalo to pay by bank transfer.",
    "notable_phrases": [{"original": "màu ngà", "literal_en": "ivory colored"},
                        {"original": "chuyển khoản", "literal_en": "bank transfer"}],
}


class Market:
    def __init__(self, listing):
        self.listing = listing

    async def get_listing_snapshot(self, listing_id):
        return self.listing


class FakeJson:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def __call__(self, **kw):
        self.calls.append(kw)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def setup(monkeypatch, answer=None, **listing_kw):
    fake = FakeJson(TRANSLATION if answer is None else answer)
    monkeypatch.setattr(llm, "call_json", fake)
    kw = dict(language="vi", title="Tượng điêu khắc cổ màu ngà", description="Gia đình để lại, chuyển khoản trước")
    listing = make_listing(**{**kw, **listing_kw})
    return Translator(Market(listing)), fake


def call():
    return SpecialistCall(case_id="C-1", listing_id="L0101", capability="translation")


def test_identity_matches_the_contract():
    t = Translator(Market(make_listing()))
    assert (t.name, t.capability, t.tier, t.model) == ("deadlang-translator", "translation", "preferred",
                                                      config.MODEL_TRIAGE)
    assert isinstance(t, Specialist)


async def test_english_listing_is_refused_without_a_model_call(monkeypatch):
    t, fake = setup(monkeypatch, language="en")
    reply = await t.run(call())
    assert (reply.ok, reply.error, reply.drafts) == (False, "already_english", [])
    assert fake.calls == []


async def test_vietnamese_listing_produces_a_draft(monkeypatch):
    t, fake = setup(monkeypatch)

    reply = await t.run(call())

    assert reply.ok and len(reply.drafts) == 1
    d = reply.drafts[0]
    assert (d.capability, d.produced_by, d.confidence, d.specialist_name) == \
        ("translation", "model", None, "deadlang-translator")
    assert d.summary == 'Translated from Vietnamese: "Old carved figurine, ivory colored, family collection".'
    assert d.data["title_en"] == TRANSLATION["title_en"]
    assert d.data["description_en"] == TRANSLATION["description_en"]
    assert d.data["notable_phrases"] == TRANSLATION["notable_phrases"]
    assert d.data["source_language"] == "Vietnamese" and d.data["language_code"] == "vi"
    assert d.data["listing_id"] == "L0101"
    assert len(fake.calls) == 1


async def test_model_call_gets_the_listing_text_and_the_right_settings(monkeypatch):
    t, fake = setup(monkeypatch)
    await t.run(call())
    c = fake.calls[0]
    assert c["model"] == config.MODEL_TRIAGE and c["case_id"] == "C-1" and c["schema_name"] == "report_translation"
    assert "Tượng điêu khắc cổ màu ngà" in c["user"] and "chuyển khoản trước" in c["user"]
    assert "Do not judge legality" in c["system"]
    assert set(c["schema"]["required"]) == {"title_en", "description_en", "notable_phrases"}


async def test_unknown_language_code_is_shown_as_is(monkeypatch):
    t, _ = setup(monkeypatch, language="xx")
    d = (await t.run(call())).drafts[0]
    assert d.summary.startswith("Translated from xx:")


async def test_notable_phrases_are_capped_at_five_and_cleaned(monkeypatch):
    messy = {**TRANSLATION, "notable_phrases": [{"original": f"p{i}", "literal_en": f"e{i}"} for i in range(8)]
             + [{"original": "no translation"}, "not a dict"]}
    t, _ = setup(monkeypatch, messy)
    phrases = (await t.run(call())).drafts[0].data["notable_phrases"]
    assert [p["original"] for p in phrases] == ["p0", "p1", "p2", "p3", "p4"]


async def test_numbers_in_the_summary_are_stored_in_data(monkeypatch):
    t, _ = setup(monkeypatch, {**TRANSLATION, "title_en": "Netsuke 18th century, 2 pieces"})
    d = (await t.run(call())).drafts[0]
    stored = set(numbers_from_text(d.data["title_en"]))
    assert set(numbers_from_text(d.summary)) <= stored


async def test_budget_exceeded_becomes_budget_error(monkeypatch):
    t, _ = setup(monkeypatch, BudgetExceeded("cap"))
    reply = await t.run(call())
    assert (reply.ok, reply.error) == (False, "budget")
