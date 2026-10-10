"""MarketplaceClient: how every other module reads the marketplace (contract: plan 01 §4.1).

Two implementations with identical behavior:
- LocalMarketplaceClient — calls the in-process store (tests and MARKETPLACE_MODE=local).
- McpMarketplaceClient   — talks to the marketplace MCP server (MARKETPLACE_MODE=mcp), so every
  process sees the same removed/relisted state.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from deadlang.marketplace.store import ListingRemoved, MarketplaceStore
from deadlang.schemas import Listing, Seller

__all__ = ["MarketplaceClient", "LocalMarketplaceClient", "McpMarketplaceClient", "ListingRemoved",
           "get_marketplace_client", "data_dir", "setting"]

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def setting(name: str, default: str) -> str:
    """A config value: deadlang.config (which loads .env) if it defines it, else the environment."""
    try:
        import deadlang.config as config
        return str(getattr(config, name))
    except (ImportError, AttributeError):
        return os.environ.get(name, default)


def data_dir() -> Path:
    """The data/ folder: config.DATA_DIR, else DL_DATA_DIR (relative to backend/), else <repo>/data."""
    try:
        from deadlang.config import DATA_DIR
        return Path(DATA_DIR)
    except (ImportError, AttributeError):
        return (_BACKEND_DIR / os.environ.get("DL_DATA_DIR", "../data")).resolve()


class MarketplaceClient(Protocol):
    async def get_listing(self, listing_id: str) -> Listing: ...            # raises ListingRemoved
    async def get_listing_snapshot(self, listing_id: str) -> Listing: ...   # any status; used only by intake
    async def get_seller(self, seller_id: str) -> Seller: ...
    async def get_seller_inventory(self, seller_id: str) -> list[Listing]: ...   # active + removed
    async def search(self, query: str, limit: int = 50) -> list[Listing]: ...
    async def all_active(self) -> list[Listing]: ...
    async def remove_listing(self, listing_id: str) -> str | None: ...      # returns revealed relist id
    async def reset_demo(self) -> None: ...
    def image_path(self, rel_path: str) -> Path: ...                        # absolute path on disk


class LocalMarketplaceClient:
    """Unknown ids raise KeyError. Returned models are copies, as they would be over MCP."""

    def __init__(self, store: MarketplaceStore, data_dir_: Path | None = None):
        self.store = store
        self._data_dir = Path(data_dir_) if data_dir_ else None
        self._original = store.statuses()

    async def get_listing(self, listing_id: str) -> Listing:
        return self.store.get_listing(listing_id).model_copy()

    async def get_listing_snapshot(self, listing_id: str) -> Listing:
        return self.store.get_listing_any_status(listing_id).model_copy()

    async def get_seller(self, seller_id: str) -> Seller:
        return self.store.get_seller(seller_id).model_copy()

    async def get_seller_inventory(self, seller_id: str) -> list[Listing]:
        return [l.model_copy() for l in self.store.seller_listings(seller_id, include_removed=True)]

    async def search(self, query: str, limit: int = 50) -> list[Listing]:
        return [l.model_copy() for l in self.store.search(query, limit)]

    async def all_active(self) -> list[Listing]:
        return [l.model_copy() for l in self.store.active_listings()]

    async def remove_listing(self, listing_id: str) -> str | None:
        return self.store.remove_listing(listing_id)

    async def reset_demo(self) -> None:
        self.store.reset_demo_state(self._original)

    def image_path(self, rel_path: str) -> Path:
        return (self._data_dir or data_dir()) / rel_path


class McpMarketplaceClient:
    """One MCP session, opened lazily on first use and reused.

    The session lives inside a background task because MCP's context managers must be entered and
    exited by the same task. A dropped connection is reopened once for read calls.
    """

    def __init__(self, url: str, data_dir_: Path | None = None, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout
        self._data_dir = Path(data_dir_) if data_dir_ else None
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None
        self._stop: asyncio.Event | None = None

    async def _own_session(self, ready: asyncio.Future, stop: asyncio.Event) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        try:
            async with streamable_http_client(self.url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ready.set_result(session)
                    await stop.wait()
        except Exception as exc:
            if not ready.done():
                ready.set_exception(ConnectionError(f"marketplace MCP server unreachable at {self.url}: {exc!r}"))

    async def _session(self):
        loop = asyncio.get_running_loop()
        if self._task is None or self._task.done() or self._task.get_loop() is not loop:
            self._ready, self._stop = loop.create_future(), asyncio.Event()
            self._task = loop.create_task(self._own_session(self._ready, self._stop))
        return await asyncio.shield(self._ready)

    async def aclose(self) -> None:
        task, stop, self._task = self._task, self._stop, None
        if task and not task.done() and task.get_loop() is asyncio.get_running_loop():
            stop.set()
            await asyncio.wait([task], timeout=5)

    async def _call(self, tool: str, **args: Any) -> Any:
        attempts = 1 if tool.startswith("admin_") else 2      # never replay a state-changing call
        for attempt in range(attempts):
            try:
                session = await self._session()
                result = await session.call_tool(tool, args, read_timeout_seconds=timedelta(seconds=self.timeout))
                break
            except Exception:
                await self.aclose()
                if attempt == attempts - 1:
                    raise
        text = result.content[0].text if result.content else ""
        if result.isError:
            raise RuntimeError(f"marketplace tool {tool} failed: {text}")
        payload = json.loads(text)
        if isinstance(payload, dict) and "error" in payload:
            if payload["error"] == "listing_removed":
                raise ListingRemoved(payload["listing_id"])
            if payload["error"] == "not_found":
                raise KeyError(payload.get("listing_id") or payload.get("seller_id"))
            raise RuntimeError(f"marketplace tool {tool} failed: {payload}")
        return payload

    async def get_listing(self, listing_id: str) -> Listing:
        return Listing.model_validate(await self._call("get_listing", listing_id=listing_id))

    async def get_listing_snapshot(self, listing_id: str) -> Listing:
        return Listing.model_validate(await self._call("get_listing_snapshot", listing_id=listing_id))

    async def get_seller(self, seller_id: str) -> Seller:
        return Seller.model_validate(await self._call("get_seller", seller_id=seller_id))

    async def get_seller_inventory(self, seller_id: str) -> list[Listing]:
        return [Listing.model_validate(r) for r in await self._call("get_seller_inventory", seller_id=seller_id)]

    async def search(self, query: str, limit: int = 50) -> list[Listing]:
        return [Listing.model_validate(r) for r in await self._call("search_listings", query=query, limit=limit)]

    async def all_active(self) -> list[Listing]:
        return [Listing.model_validate(r) for r in await self._call("list_active")]

    async def remove_listing(self, listing_id: str) -> str | None:
        return (await self._call("admin_remove_listing", listing_id=listing_id))["relisted_as"]

    async def reset_demo(self) -> None:
        await self._call("admin_reset_demo")

    def image_path(self, rel_path: str) -> Path:
        return (self._data_dir or data_dir()) / rel_path


_client: MarketplaceClient | None = None


def get_marketplace_client() -> MarketplaceClient:
    """Process-wide singleton: MCP client if MARKETPLACE_MODE=mcp, else the local in-process one."""
    global _client
    if _client is None:
        if setting("MARKETPLACE_MODE", "local").strip().lower() == "mcp":
            _client = McpMarketplaceClient(setting("MARKETPLACE_MCP_URL", "http://localhost:8100/mcp"))
        else:
            _client = LocalMarketplaceClient(MarketplaceStore.from_dir(data_dir()))
    return _client
