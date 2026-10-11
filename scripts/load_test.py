"""Run a real live batch against a running API and record measured speed. Costs real model money.

  python scripts/load_test.py --api http://localhost:8010 --query "carved bone" --cap 10
Writes results/load_test.json. Every number in it is measured here, none estimated.
"""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

ap = argparse.ArgumentParser()
ap.add_argument("--api", default="http://localhost:8000")
ap.add_argument("--query", default="carved bone")
ap.add_argument("--cap", type=int, default=10)
ap.add_argument("--timeout", type=int, default=900)
a = ap.parse_args()


def call(path, body=None):
    r = Request(a.api + path, json.dumps(body).encode() if body is not None else None, {"content-type": "application/json"})
    return json.load(urlopen(r, timeout=120))


t0 = time.time()
b = call("/api/batches", {"source": "live", "query": a.query, "cap": a.cap})
t_fetch = time.time() - t0
while time.time() - t0 < a.timeout:
    cur = call(f"/api/batches/{b['batch_id']}")
    if all(i["status"] in ("done", "error", "screened_out") for i in cur["items"]):
        break
    time.sleep(3)
total = time.time() - t0
m = call("/api/metrics")
res = {"batch_id": b["batch_id"], "source_mode": b["source_mode"], "query": a.query, "items": len(cur["items"]),
       "done": sum(i["status"] == "done" for i in cur["items"]), "errors": sum(i["status"] == "error" for i in cur["items"]),
       "fetch_s": round(t_fetch, 1), "total_s": round(total, 1), "listings_per_min": round(len(cur["items"]) / total * 60, 2),
       "outcomes": {o: sum(i["outcome"] == o for i in cur["items"]) for o in ("FILE", "CONTESTED", "WATCHLIST", "DISMISS")},
       "metrics": {k: m[k] for k in ("latency_ms", "cost", "funnel")}}
Path(__file__).resolve().parents[1].joinpath("results/load_test.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
