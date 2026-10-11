"""Serve agents as A2A servers over SLIM (plan 03 Task 6).

    uv run python -m deadlang.agntcy.serve --group <specialists|examiner-thorough|examiner-quick|deliberators|all>

Each agent gets its own A2A server on its own SLIM identity, default/default/<agent name>, with its
AgentCard from cards.py. The executor reads the request's text part (a SpecialistCall, a DeliberationTurn,
or a broadcast payload {"kind": "turns", "turns": {...}} from which a deliberator takes its own entry),
calls the plain handler (Specialist.run / DeliberatingAgent.handle) and replies with one text part holding
the reply model's JSON. Failures are replies too, never a crash of the server.

When DISCOVERY=agntcy the process pushes its own agents' cards to the AGNTCY Directory after its servers
are up, so the Directory lists the agents that are actually running.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Awaitable, Callable

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import new_agent_text_message
from pydantic import ValidationError

from deadlang import config
from deadlang.agntcy.cards import DELIBERATOR_NAMES, card_for
from deadlang.agntcy.transport import error_text, timeout_for
from deadlang.agntcy.wire import slim_name
from deadlang.llm import BudgetExceeded
from deadlang.schemas import AgentName, DeliberationTurn, SpecialistCall, SpecialistReply

log = logging.getLogger("deadlang.serve")

Handler = Callable[[str], Awaitable[str]]

GROUPS: dict[str, list[str]] = {
    "specialists": ["deadlang-price-checker", "deadlang-seller-inventory", "deadlang-linked-sellers",
                    "deadlang-legal-table", "deadlang-translator"],
    "examiner-thorough": ["deadlang-examiner-thorough"],     # its own process so it can be killed in the demo
    "examiner-quick": ["deadlang-examiner-quick"],
    "deliberators": list(DELIBERATOR_NAMES.values()),
}
GROUPS["all"] = [name for group in list(GROUPS.values()) for name in group]

AGENT_BY_SERVER_NAME: dict[str, AgentName] = {v: k for k, v in DELIBERATOR_NAMES.items()}
SPECIALIST_TIMEOUT = 45.0      # server-side caps match the transport's defaults, so no work outlives its caller
AGENT_TIMEOUT = 90.0
START_TIMEOUT = 20.0          # seconds to connect every server to SLIM


# ---------------------------------------------------------------- handlers (plain async str -> str)

def specialist_handler(specialist: Any) -> Handler:
    async def handle(text: str) -> str:
        try:
            call = SpecialistCall.model_validate_json(text)
        except ValidationError as exc:
            return SpecialistReply(ok=False, error=f"bad request: {exc.errors()[0]['msg']}").model_dump_json()
        try:
            reply = await asyncio.wait_for(specialist.run(call), timeout_for(specialist.name, SPECIALIST_TIMEOUT))
        except BudgetExceeded:
            reply = SpecialistReply(ok=False, error="budget")
        except Exception as exc:
            log.warning("specialist %s failed: %r", specialist.name, exc)
            reply = SpecialistReply(ok=False, error=error_text(exc))
        return reply.model_dump_json()
    return handle


def deliberator_handler(agent_name: AgentName, agent: Any) -> Handler:
    def error(message: str, budget: bool = False) -> str:
        return json.dumps({"agent": agent_name, "error": message, **({"budget": True} if budget else {})})

    async def handle(text: str) -> str:
        try:
            data = json.loads(text)
        except ValueError:
            return error("bad request: not JSON")
        if isinstance(data, dict) and data.get("kind") == "turns":      # a broadcast: take our own entry
            data = (data.get("turns") or {}).get(agent_name)
            if data is None:
                return error("no turn for this agent in the broadcast")
        try:
            turn = DeliberationTurn.model_validate(data)
        except ValidationError as exc:
            return error(f"bad request: {exc.errors()[0]['msg']}")
        try:
            post = await asyncio.wait_for(agent.handle(turn), AGENT_TIMEOUT)
        except BudgetExceeded as exc:
            return error(str(exc) or "budget", budget=True)
        except Exception as exc:
            log.warning("agent %s failed: %r", agent_name, exc)
            return error(error_text(exc))
        return post.model_dump_json()
    return handle


# ---------------------------------------------------------------- A2A plumbing

class JsonExecutor(AgentExecutor):
    """Reads the request's text, runs the handler, replies with one text message."""

    def __init__(self, handle: Handler):
        self._handle = handle

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        reply = await self._handle(context.get_user_input())
        await event_queue.enqueue_event(
            new_agent_text_message(reply, context_id=context.context_id, task_id=context.task_id))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is not supported")


def build_app(name: str, handle: Handler) -> A2AStarletteApplication:
    return A2AStarletteApplication(
        agent_card=card_for(name),
        http_handler=DefaultRequestHandler(agent_executor=JsonExecutor(handle), task_store=InMemoryTaskStore()))


def build_handlers(names: list[str], market: Any = None) -> dict[str, Handler]:
    """Real handlers for the named agents: specialists from the registry, deliberators from deliberation."""
    handlers: dict[str, Handler] = {}
    wanted_specialists = [n for n in names if n not in AGENT_BY_SERVER_NAME]
    if wanted_specialists:
        from deadlang.specialists.registry import build_specialists
        if market is None:
            from deadlang.marketplace.client import get_marketplace_client
            market = get_marketplace_client()
        built = {s.name: s for s in build_specialists(market)}
        for name in wanted_specialists:
            if name not in built:
                raise RuntimeError(f"{name} is not available (the registry could not build it)")
            handlers[name] = specialist_handler(built[name])
    for name in names:
        if name in AGENT_BY_SERVER_NAME:
            from deadlang.deliberation.agents import DeliberatingAgent
            agent_name = AGENT_BY_SERVER_NAME[name]
            handlers[name] = deliberator_handler(agent_name, DeliberatingAgent(agent_name))
    return handlers


async def start(handlers: dict[str, Handler], *, factory: Any = None) -> Any:
    """Start one A2A server over SLIM per handler; returns the AppSession (call stop_all_sessions() to stop)."""
    from agntcy_app_sdk import AgntcyFactory

    factory = factory or AgntcyFactory("deadlang-serve")
    session = factory.create_app_session(max_sessions=len(handlers))
    for name, handle in handlers.items():
        link = factory.create_transport("SLIM", endpoint=config.SLIM_ENDPOINT, name=slim_name(name),
                                        shared_secret_identity=config.SLIM_SHARED_SECRET)
        session.add(build_app(name, handle)).with_transport(link).with_topic(slim_name(name)) \
            .with_session_id(name).build()
    try:                                  # the SLIM bindings retry a refused connection forever
        await asyncio.wait_for(session.start_all_sessions(keep_alive=False), START_TIMEOUT)
    except asyncio.TimeoutError:
        raise ConnectionError(f"SLIM did not answer within {START_TIMEOUT:.0f} s") from None
    return session


async def run_many(names: list[str]) -> int:
    """One OS process per agent: several A2A servers in one process share one SLIM connection and only one answers."""
    procs = [await asyncio.create_subprocess_exec(sys.executable, "-m", "deadlang.agntcy.serve", "--agent", n)
             for n in names]
    try:
        await asyncio.gather(*(p.wait() for p in procs))
    finally:
        for p in procs:
            if p.returncode is None:
                p.terminate()
    return 0


async def run_group(group: str) -> int:
    names = GROUPS[group] if group in GROUPS else [group]
    if len(names) > 1:
        return await run_many(names)
    handlers = build_handlers(names)
    try:
        session = await start(handlers)
    except Exception as exc:
        print(f"Could not start the {group} servers on SLIM at {config.SLIM_ENDPOINT}: {exc}\n"
              "Is SLIM up?  docker compose -f infra/docker-compose.yaml up -d", file=sys.stderr)
        return 2
    print(f"Serving {', '.join(names)} over SLIM at {config.SLIM_ENDPOINT}.", flush=True)
    if config.DISCOVERY == "agntcy":
        from deadlang.agntcy.discovery import AgntcyDirectoryDiscovery
        try:
            await AgntcyDirectoryDiscovery().register(names)
            print(f"Registered {len(names)} AgentCard(s) in the AGNTCY Directory at {config.DIRECTORY_ADDRESS}.",
                  flush=True)
        except Exception as exc:
            print(f"WARNING: could not register in the AGNTCY Directory at {config.DIRECTORY_ADDRESS}: {exc}. "
                  "The servers are up; discovery will fall back to local cards.", file=sys.stderr, flush=True)
    try:
        await asyncio.Event().wait()            # until Ctrl+C / the process is stopped
    finally:
        await session.stop_all_sessions()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve Watchdog agents as A2A servers over SLIM.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--group", choices=list(GROUPS))
    which.add_argument("--agent", choices=GROUPS["all"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        return asyncio.run(run_group(args.group or args.agent))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
