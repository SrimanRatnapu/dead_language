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

    b = Batches(worker, "fake", limit=1)
    batch = b.submit("demo", ["L1", "BAD", "L2", "L1"])        # duplicate id is collapsed
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

    b = Batches(worker, "fake", limit=2)
    await collect(b, b.submit("demo", [f"L{i}" for i in range(6)])["batch_id"])
    assert peak == 2


@pytest.fixture
def client(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "demo_cases.json").write_text(json.dumps({"d1": "L0101", "d2": "L0102"}))
    t = FakeTransport(posts={(a, 1): post(a, 1, "file") for a in ("undercover", "counsel", "case_officer")})
    app = create_app(FakeMarket(), t, FakeDiscovery(), EventBus(runs_dir=tmp_path / "runs"), data_dir=tmp_path / "data",
                     replays_dir=tmp_path / "r", results_dir=tmp_path / "res", worker_mode="real")
    with TestClient(app) as c:
        yield c


def test_batch_api_runs_real_cases_and_streams_to_the_end(client):
    r = client.post("/api/batches", json={"source": "demo"})         # no ids: the demo set
    assert r.status_code == 202
    body = r.json()
    assert body["mode"] == "real" and [i["status"] for i in body["items"]] == ["queued", "queued"]
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
    assert client.post("/api/batches", json={"source": "live", "query": "ivory"}).status_code == 501
    assert client.post("/api/batches", json={"source": "demo", "cap": 0}).status_code == 422
    assert client.get("/api/batches/B-9999").status_code == 404
    assert client.get("/api/batches/B-9999/events").status_code == 404
