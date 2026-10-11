import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from deadlang.api.batches import Batches
from deadlang.api.events import EventBus
from deadlang.api.server import create_app
from tests.fakes import FakeDiscovery, FakeMarket, FakeTransport, post


async def collect(batches, bid):
    return [e async for e in batches.events(bid)]


async def test_one_bad_item_does_not_fail_batch_and_late_subscriber_sees_history():
    async def worker(item, set_status):
        set_status(status="deliberating")
        if item["listing_id"] == "BAD":
            raise ValueError("boom")
        set_status(status="done", outcome="FILE")

    b = Batches(worker, limit=1)
    batch = b.submit("demo", ["L1", "BAD", "L2", "L1"], "demo")        # duplicate id is collapsed
    assert [i["listing_id"] for i in batch["items"]] == ["L1", "BAD", "L2"]
    first = await collect(b, batch["batch_id"])                  # subscribes mid-run, ends when all terminal
    late = await collect(b, batch["batch_id"])                   # subscribes after the end: full replay
    assert first == late
    got = {i["listing_id"]: i for i in b.view(batch["batch_id"])["items"]}
    assert got["BAD"]["status"] == "error" and "boom" in got["BAD"]["error"]
    assert got["L1"]["outcome"] == got["L2"]["outcome"] == "FILE"
    assert [e["status"] for e in late if e["listing_id"] == "L1"] == ["queued", "deliberating", "done"]


async def test_concurrency_limit_is_respected():
    running = peak = 0

    async def worker(item, set_status):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        set_status(status="done", outcome="DISMISS")

    b = Batches(worker, limit=2)
    await collect(b, b.submit("demo", [f"L{i}" for i in range(6)], "demo")["batch_id"])
    assert peak == 2


@pytest.fixture
def client(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "demo_cases.json").write_text(json.dumps({"d1": "L0101", "d2": "L0102"}))
    t = FakeTransport(posts={(a, 1): post(a, 1, "file") for a in ("undercover", "counsel", "case_officer")})
    app = create_app(FakeMarket(), t, FakeDiscovery(), EventBus(runs_dir=tmp_path / "runs"), data_dir=tmp_path / "data",
                     replays_dir=tmp_path / "r", results_dir=tmp_path / "res")
    with TestClient(app) as c:
        yield c


def test_batch_api_runs_real_cases_and_streams_to_the_end(client):
    r = client.post("/api/batches", json={"source": "demo"})         # no ids: the demo set
    assert r.status_code == 202
    body = r.json()
    assert body["source_mode"] == "demo" and [i["status"] for i in body["items"]] == ["queued", "queued"]
    statuses = []
    with client.stream("GET", f"/api/batches/{body['batch_id']}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:"):
                statuses.append(json.loads(line[5:]))
    assert {e["listing_id"] for e in statuses} == {"L0101", "L0102"}
    final = client.get(f"/api/batches/{body['batch_id']}").json()
    assert all(i["status"] == "done" and i["outcome"] == "FILE" and i["case_id"] for i in final["items"])
    assert client.get(f"/api/cases/{final['items'][0]['case_id']}/casefile").status_code == 200


def test_batch_api_rejects_bad_requests(client):
    assert client.post("/api/batches", json={"source": "demo", "cap": 0}).status_code == 422
    assert client.post("/api/batches", json={"source": "live", "query": "x", "cap": 51}).status_code == 422
    assert client.get("/api/batches/B-9999").status_code == 404
    assert client.get("/api/batches/B-9999/events").status_code == 404


def run_batch(client):
    b = client.post("/api/batches", json={"source": "demo"}).json()
    with client.stream("GET", f"/api/batches/{b['batch_id']}/events") as s:
        list(s.iter_lines())
    return client.get(f"/api/batches/{b['batch_id']}").json()["items"]


def test_metrics_are_zero_before_runs_then_measured(client):
    m = client.get("/api/metrics").json()
    assert m["funnel"]["ingested"] == 0 and m["cost"]["usd_total"] == 0
    run_batch(client)
    m = client.get("/api/metrics").json()
    assert m["funnel"]["ingested"] == 2 and m["funnel"]["FILE"] == 2


def test_spend_cap_stops_new_cases(client, monkeypatch):
    from deadlang import config
    monkeypatch.setattr(config, "MAX_SPEND_USD", 1.0)
    from deadlang import llm
    llm.usage_hook("claude-sonnet-5-5", "x", None, 1_000_000, 1_000_000, 1)   # $12 of recorded spend
    items = run_batch(client)
    assert all(i["status"] == "error" and "spend cap" in i["error"] for i in items)


def test_batch_ids_continue_after_restart():
    async def w(item, set_status):
        set_status(status="done", outcome="FILE")
    assert Batches(w, first_id=7).submit("demo", [], "demo")["batch_id"] == "B-0007"


def test_health_reports_unreachable_services(client, monkeypatch):
    from deadlang import config
    monkeypatch.setattr(config, "TRANSPORT", "agntcy")
    monkeypatch.setattr(config, "SLIM_ENDPOINT", "http://127.0.0.1:1")
    monkeypatch.setattr(config, "DIRECTORY_ADDRESS", "127.0.0.1:1")
    h = client.get("/api/health").json()
    assert len(h["problems"]) == 2 and "SLIM" in h["problems"][0]


def test_live_batch_reports_fetch_mode(client, monkeypatch):
    from deadlang.marketplace import live
    listing = FakeMarket().listing

    async def fake_fetch(query, cap, sweep=None):
        return [(listing, None)], "recorded"

    async def fake_rank(ids):
        return [{"listing_id": i} for i in ids]
    monkeypatch.setattr(live, "fetch_live", fake_fetch)
    monkeypatch.setattr(live, "rank_for_review", fake_rank)
    r = client.post("/api/batches", json={"source": "live", "query": "x"})
    assert r.status_code == 202 and r.json()["source_mode"] == "recorded"
    assert [i["listing_id"] for i in r.json()["items"]] == [listing.id]


def test_added_listing_jumps_the_queue_or_starts_its_own_batch():
    import asyncio
    from deadlang.api.batches import Batches
    from deadlang.marketplace.live import parse_item_ref
    started: list[str] = []

    async def worker(item, set_status):
        started.append(item["listing_id"])
        await asyncio.sleep(0.01)
        set_status(status="done", outcome="DISMISS")

    async def go():
        b = Batches(worker, limit=1)
        first = b.submit("live", ["A", "B", "C"], "live")
        added = b.add("Z", "live", "live")
        assert not added["new_batch"] and added["batch_id"] == first["batch_id"]
        assert not b.add("Z", "live", "live")["new_batch"]       # same listing again: no second review
        async for _ in b.events(first["batch_id"]):
            pass
        idle = b.add("Y", "live", "live")
        assert idle["new_batch"] and idle["batch_id"] != first["batch_id"]
        async for _ in b.events(idle["batch_id"]):
            pass

    asyncio.run(go())
    assert started == ["A", "Z", "B", "C", "Y"]               # A already held the only slot; Z beat B and C
    assert [parse_item_ref(r) for r in ("https://www.ebay.com/itm/Old-Netsuke/123456789012?hash=x", "v1|123456789012|0", " 123456789012 ", "LV0342")] \
        == ["123456789012"] * 3 + [None]


def test_queue_add_takes_a_listing_id_and_rejects_junk(client):
    lid = run_batch(client)[0]["listing_id"]
    assert client.post("/api/queue/add", json={"ref": "not a listing"}).status_code == 422
    r = client.post("/api/queue/add", json={"ref": f" {lid} "})
    assert r.status_code == 202 and r.json()["item"]["listing_id"] == lid and r.json()["new_batch"]
