import asyncio
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deadlang.api.events import EventBus
from deadlang.api.server import create_app
from tests.fakes import FakeDiscovery, FakeMarket, FakeTransport, post

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_case_events.jsonl"


def slow_transport(delay=0.4):
    t = FakeTransport(posts={(a, 1): post(a, 1, "file") for a in ("undercover", "counsel", "case_officer")})

    async def pause(r):
        await asyncio.sleep(delay)
    t.on_broadcast = pause
    return t


@pytest.fixture
def env(tmp_path):
    (tmp_path / "data" / "images").mkdir(parents=True)
    (tmp_path / "data" / "images" / "a.jpg").write_bytes(b"jpg")
    (tmp_path / "secret.txt").write_text("secret")
    (tmp_path / "data" / "triage.json").write_text(json.dumps({"L0101": {"score": 0.8, "reason": "price", "price_ratio": 15.3}}))
    (tmp_path / "replays").mkdir()
    shutil.copy(FIXTURE, tmp_path / "replays" / "d1_network.jsonl")
    transport = slow_transport()
    app = create_app(FakeMarket(), transport, FakeDiscovery(), EventBus(runs_dir=tmp_path / "runs"),
                     data_dir=tmp_path / "data", replays_dir=tmp_path / "replays", results_dir=tmp_path / "results")
    with TestClient(app) as client:
        yield client, tmp_path, transport


def stream_types(client, case_id):
    out = []
    with client.stream("GET", f"/api/cases/{case_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event:"):
                out.append(line.split(":", 1)[1].strip())
    return out


def test_case_stream_runs_through_case_ended_and_casefile_appears_after(env):
    client, tmp, _ = env
    case_id = client.post("/api/cases", json={"listing_id": "L0101"}).json()["case_id"]
    assert case_id == "C-0001"
    assert client.get(f"/api/cases/{case_id}/casefile").status_code == 404      # still running
    types = stream_types(client, case_id)
    assert types[0] == "case.started" and types[-1] == "case.ended" and "stance.posted" in types
    cf = client.get(f"/api/cases/{case_id}/casefile")
    assert cf.status_code == 200 and cf.json()["outcome"] == "FILE"
    assert client.get("/api/cases").json()[0]["outcome"] == "FILE"
    assert (tmp / "runs" / "C-0001.jsonl").exists()                             # replay log written
    assert client.get("/api/cases/C-9999/events").status_code == 404


def test_remove_listing_reaches_running_case(env):
    client, _, _ = env
    case_id = client.post("/api/cases", json={"listing_id": "L0101"}).json()["case_id"]
    import time; time.sleep(0.1)
    r = client.post("/api/demo/remove-listing", json={"listing_id": "L0101"}).json()
    assert r == {"removed": "L0101", "relisted_as": "L0456"}
    assert "listing.removed" in stream_types(client, case_id)


def test_image_serving_and_traversal(env):
    client, _, _ = env
    assert client.get("/api/images/images/a.jpg").content == b"jpg"
    assert client.get("/api/images/images/missing.jpg").status_code == 404
    for evil in ("../secret.txt", "..%2fsecret.txt", "%2e%2e/secret.txt", "images/../../secret.txt"):
        assert client.get(f"/api/images/{evil}").status_code != 200, evil


def test_replays_listings_kill_and_eval(env):
    client, tmp, transport = env
    assert client.get("/api/replays").json() == ["d1_network"]
    events = client.get("/api/replays/d1_network").json()
    assert events[0]["type"] == "case.started" and events[-1]["type"] == "case.ended"
    assert client.get("/api/replays/nope").status_code == 404
    assert client.get("/api/replays/..%2fsecret").status_code == 404

    rows = client.get("/api/listings?sort=triage").json()
    assert rows[0]["triage"] == {"score": 0.8, "reason": "price"} and rows[0]["seller"]["id"] == "S0042"
    assert client.get("/api/listings/L0101").json()["listing"]["id"] == "L0101"

    assert client.post("/api/demo/kill-specialist", json={"name": "deadlang-examiner-thorough"}).json() == {"ok": True}
    assert client.post("/api/demo/reset").json() == {"ok": True}
    assert client.get("/api/eval").status_code == 404
    (tmp / "results").mkdir()
    (tmp / "results" / "eval.json").write_text('{"n_pos": 3}')
    assert client.get("/api/eval").json() == {"n_pos": 3}


def test_unknown_listing_is_rejected_and_crashing_case_still_ends_stream(env, tmp_path):
    client, _, _ = env
    class Boom(FakeMarket):
        calls = 0
        async def get_listing_snapshot(self, listing_id):
            if listing_id != "L0101":
                raise KeyError(listing_id)
            Boom.calls += 1
            if Boom.calls > 1:                     # first call is the precheck; run_case's call blows up
                raise RuntimeError("market down")
            return self.listing
    app = create_app(Boom(), FakeTransport(), FakeDiscovery(), EventBus(runs_dir=None),
                     data_dir=tmp_path / "data", replays_dir=tmp_path / "replays", results_dir=tmp_path / "results")
    with TestClient(app) as c:
        assert c.post("/api/cases", json={"listing_id": "NOPE"}).status_code == 404
        cid = c.post("/api/cases", json={"listing_id": "L0101"}).json()["case_id"]
        with c.stream("GET", f"/api/cases/{cid}/events") as r:
            data = [l for l in r.iter_lines() if l.startswith("data:")]
        assert '"error"' in data[-1] and "market down" in data[-1]
