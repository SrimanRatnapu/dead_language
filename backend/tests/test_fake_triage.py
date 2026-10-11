"""FakeTriage: what C builds the queue worker against. It behaves like the real screen() (file 00 section 4.5)."""
import pytest

from deadlang.llm import BudgetExceeded
from deadlang.schemas import TriageResult
from tests.fakes import FakeTriage, make_listing


async def test_it_returns_a_triage_result_with_the_three_contract_fields():
    result = await FakeTriage().screen(make_listing())
    assert isinstance(result, TriageResult)
    assert set(result.model_dump()) == {"score", "reason", "suspicious"}
    assert 0.0 <= result.score <= 1.0 and result.reason


async def test_scores_are_per_listing_and_the_threshold_decides_suspicious():
    fake = FakeTriage(scores={"L0101": 0.05, "L0202": 0.6}, default=0.3, threshold=0.2)
    assert (await fake.screen(make_listing(id="L0101"))).suspicious is False      # below the threshold: cleared
    assert (await fake.screen(make_listing(id="L0202"))).suspicious is True
    assert (await fake.screen(make_listing(id="L0303"))).score == 0.3             # the default
    assert (await fake.screen(make_listing(id="L0404"))).suspicious is True       # 0.3 >= 0.2


async def test_a_score_exactly_at_the_threshold_is_sent_on():
    assert (await FakeTriage(default=0.2, threshold=0.2).screen(make_listing())).suspicious is True


async def test_it_records_what_it_was_asked():
    fake = FakeTriage()
    await fake.screen(make_listing(id="L1"), None, price_ratio=3.2, seller_listing_count=7)
    await fake(make_listing(id="L2"))                                             # also callable like screen()
    assert [c["listing_id"] for c in fake.calls] == ["L1", "L2"]
    assert fake.calls[0]["price_ratio"] == 3.2 and fake.calls[0]["seller_listing_count"] == 7


async def test_it_can_raise_like_the_real_one_does_for_a_spent_budget():
    fake = FakeTriage(raises={"L9": BudgetExceeded("global input cap reached")})
    with pytest.raises(BudgetExceeded):
        await fake.screen(make_listing(id="L9"))
    assert (await fake.screen(make_listing(id="L1"))).reason                       # other listings are unaffected


async def test_it_can_be_slow_so_a_worker_can_be_tested_with_concurrency():
    import asyncio
    import time
    fake = FakeTriage(delay=0.05)
    start = time.perf_counter()
    await asyncio.gather(*[fake.screen(make_listing(id=f"L{i}")) for i in range(4)])
    assert time.perf_counter() - start < 0.15                                      # ran together, not one after another


async def test_it_accepts_the_same_threshold_override_as_the_real_one():
    fake = FakeTriage(default=0.3, threshold=0.2)
    assert (await fake.screen(make_listing(), threshold=0.5)).suspicious is False
    assert (await fake.screen(make_listing())).suspicious is True
