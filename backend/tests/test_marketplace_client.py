import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deadlang.marketplace import client as client_mod
from deadlang.marketplace.client import (ListingRemoved, LocalMarketplaceClient, McpMarketplaceClient,
                                         get_marketplace_client)

BACKEND = Path(__file__).resolve().parents[1]
IDS, SELLERS = ("L1", "L2", "L3", "L4"), ("S1", "S2", "S3")


async def check_every_method(c, data_dir: Path):
    """The same expectations hold for the local and the MCP client."""
    assert (await c.get_listing("L1")).title == "Carved bone netsuke"
    assert (await c.get_listing_snapshot("L4")).status == "hidden"
    with pytest.raises(KeyError):
        await c.get_listing("L4")                      # hidden = does not exist yet
    with pytest.raises(KeyError):
        await c.get_listing("L999")
    with pytest.raises(KeyError):
        await c.get_seller("S999")
    assert (await c.get_seller("S1")).name == "seller_s1"
    assert [l.id for l in await c.get_seller_inventory("S1")] == ["L1", "L2"]
    assert [l.id for l in await c.search("bone netsuke")] == ["L1"]
    assert [l.id for l in await c.search("bone", limit=1)] == ["L1"]
    assert [l.id for l in await c.all_active()] == ["L1", "L2", "L3"]

    assert await c.remove_listing("L1") == "L4"
    with pytest.raises(ListingRemoved) as exc:
        await c.get_listing("L1")
    assert exc.value.listing_id == "L1"
    assert (await c.get_listing_snapshot("L1")).status == "removed"
    assert [l.id for l in await c.get_seller_inventory("S1")] == ["L1", "L2"]   # removed still listed
    assert [l.id for l in await c.all_active()] == ["L2", "L3", "L4"]
    assert await c.remove_listing("L3") is None
    with pytest.raises(KeyError):
        await c.remove_listing("L999")

    await c.reset_demo()
    assert [l.id for l in await c.all_active()] == ["L1", "L2", "L3"]
    assert c.image_path("images/L1_0.jpg") == data_dir / "images" / "L1_0.jpg"


async def test_local_client(store, tmp_path):
    await check_every_method(LocalMarketplaceClient(store, tmp_path), tmp_path)


async def test_local_client_returns_copies(store):
    c = LocalMarketplaceClient(store)
    snapshot = await c.get_listing_snapshot("L1")
    await c.remove_listing("L1")
    assert snapshot.status == "active"                 # a snapshot stays frozen


def test_factory_defaults_to_local(store, tmp_path, monkeypatch):
    for l in IDS:
        with (tmp_path / "listings.jsonl").open("a") as f:
            f.write(store.get_listing_any_status(l).model_dump_json() + "\n")
    for s in SELLERS:
        with (tmp_path / "sellers.jsonl").open("a") as f:
            f.write(store.get_seller(s).model_dump_json() + "\n")
    monkeypatch.setattr(client_mod, "_client", None)
    monkeypatch.setattr(client_mod, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(client_mod, "setting", lambda name, default: default)
    c = get_marketplace_client()
    assert isinstance(c, LocalMarketplaceClient) and get_marketplace_client() is c
    monkeypatch.setattr(client_mod, "_client", None)
    monkeypatch.setattr(client_mod, "setting", lambda name, default: "mcp" if name == "MARKETPLACE_MODE" else default)
    assert isinstance(get_marketplace_client(), McpMarketplaceClient)


@pytest.fixture
def mcp_server(store, tmp_path):
    (tmp_path / "listings.jsonl").write_text(
        "".join(store.get_listing_any_status(i).model_dump_json() + "\n" for i in IDS))
    (tmp_path / "sellers.jsonl").write_text("".join(store.get_seller(i).model_dump_json() + "\n" for i in SELLERS))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "deadlang.marketplace.server", "--port", str(port),
                             "--data-dir", str(tmp_path)], cwd=BACKEND,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                assert proc.poll() is None, "marketplace server exited during startup"
                time.sleep(0.1)
        else:
            raise AssertionError("marketplace server did not start")
        yield f"http://127.0.0.1:{port}/mcp", tmp_path
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.integration
async def test_mcp_client_against_real_server(mcp_server):
    url, data_dir = mcp_server
    c = McpMarketplaceClient(url, data_dir)
    try:
        await check_every_method(c, data_dir)
        first_task = c._task
        await c.get_listing("L2")
        assert c._task is first_task                   # one session, reused
    finally:
        await c.aclose()


@pytest.mark.integration
async def test_mcp_client_reports_unreachable_server():
    c = McpMarketplaceClient("http://127.0.0.1:9/mcp", timeout=2)
    with pytest.raises(Exception):
        await c.get_listing("L1")
    await c.aclose()
