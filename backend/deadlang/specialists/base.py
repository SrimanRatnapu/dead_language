"""The Specialist protocol (contract: plan 01 §4.2). Every specialist, code or model, implements this."""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from deadlang.schemas import Capability, SpecialistCall, SpecialistReply

Tier = Literal["preferred", "fallback"]


@runtime_checkable
class Specialist(Protocol):
    name: str                 # AgentCard name, e.g. "deadlang-price-checker"
    capability: Capability
    tier: Tier

    async def run(self, call: SpecialistCall) -> SpecialistReply: ...
