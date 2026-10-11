"""Marketplace MCP server (FastMCP, streamable HTTP at http://localhost:8100/mcp).

Run: uv run python -m deadlang.marketplace.server [--port 8100] [--data-dir ../data]
Every tool returns a JSON string; errors come back as {"error": "...", ...}.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from deadlang.marketplace.store import ListingRemoved, MarketplaceStore
from deadlang.schemas import Listing, Seller


def _dump(models) -> str:
    return json.dumps([m.model_dump() for m in models])


def build_server(store: MarketplaceStore, host: str = "127.0.0.1", port: int = 8100) -> FastMCP:
    mcp = FastMCP("deadlang-marketplace", host=host, port=port, streamable_http_path="/mcp")
    original = store.statuses()

    def not_found(kind: str, key: str) -> str:
        return json.dumps({"error": "not_found", f"{kind}_id": key})

    @mcp.tool()
    def get_listing(listing_id: str) -> str:
        """One active listing. A removed listing returns {"error": "listing_removed"}."""
        try:
            return store.get_listing(listing_id).model_dump_json()
        except ListingRemoved:
            return json.dumps({"error": "listing_removed", "listing_id": listing_id})
        except KeyError:
            return not_found("listing", listing_id)

    @mcp.tool()
    def get_listing_snapshot(listing_id: str) -> str:
        """One listing in any status (active, removed or hidden). Used by intake only."""
        try:
            return store.get_listing_any_status(listing_id).model_dump_json()
        except KeyError:
            return not_found("listing", listing_id)

    @mcp.tool()
    def get_seller(seller_id: str) -> str:
        """One seller profile."""
        try:
            return store.get_seller(seller_id).model_dump_json()
        except KeyError:
            return not_found("seller", seller_id)

    @mcp.tool()
    def get_seller_inventory(seller_id: str) -> str:
        """All of a seller's listings, active and removed."""
        return _dump(store.seller_listings(seller_id, include_removed=True))

    @mcp.tool()
    def search_listings(query: str, limit: int = 50) -> str:
        """Active listings whose title or description contains every word of the query."""
        return _dump(store.search(query, limit))

    @mcp.tool()
    def list_active() -> str:
        """Every active listing."""
        return _dump(store.active_listings())

    @mcp.tool()
    def admin_remove_listing(listing_id: str) -> str:
        """Demo control: the seller removes a listing. Returns the id of a relist it reveals, if any."""
        try:
            return json.dumps({"removed": listing_id, "relisted_as": store.remove_listing(listing_id)})
        except KeyError:
            return not_found("listing", listing_id)

    @mcp.tool()
    def admin_add_listing(listing_json: str, seller_json: str = "") -> str:
        """Live lane: add one fetched listing (and its seller) to the running store. Nothing is written to disk."""
        store.add(Listing.model_validate_json(listing_json), Seller.model_validate_json(seller_json) if seller_json else None)
        return json.dumps({"ok": True})

    @mcp.tool()
    def market_stats() -> str:
        """Counts and median price of active listings by marketplace, country and stated material."""
        return json.dumps(store.market_stats())

    @mcp.tool()
    def admin_reset_demo() -> str:
        """Demo control: restore every listing to its status at server start."""
        store.reset_demo_state(original)
        return json.dumps({"ok": True})

    return mcp


def main() -> None:
    from deadlang.marketplace.client import data_dir, setting
    from urllib.parse import urlparse

    default_port = urlparse(setting("MARKETPLACE_MCP_URL", "http://localhost:8100/mcp")).port or 8100
    parser = argparse.ArgumentParser(description="Watchdog marketplace MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()
    store = MarketplaceStore.from_dir(args.data_dir or data_dir())
    build_server(store, args.host, args.port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
