"""Cost estimates and the y/N prompt that scripts show before making real (paid) API calls.

Prices are list prices per million tokens as of 2026-10; they are an estimate, not a bill. The token estimate
is the same one llm.py uses for its budget check, so a run that fits here will not trip the caps by surprise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from deadlang import config, llm

# model id prefix -> (input $, output $) per million tokens
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}


def price_for(model: str) -> tuple[float, float] | None:
    matches = [k for k in PRICES_PER_MTOK if model.startswith(k)]
    return PRICES_PER_MTOK[max(matches, key=len)] if matches else None


@dataclass(frozen=True)
class Batch:
    """`calls` identical-ish calls to one model. Token figures are per call."""
    label: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int          # typical
    max_output_tokens: int      # the max_tokens the call sets


@dataclass(frozen=True)
class Estimate:
    calls: int
    input_tokens: int
    output_tokens: int
    worst_output_tokens: int
    dollars: float | None           # None if any model's price is unknown
    worst_dollars: float | None


def estimate(batches: list[Batch]) -> Estimate:
    calls = sum(b.calls for b in batches)
    tin = sum(b.calls * b.input_tokens for b in batches)
    tout = sum(b.calls * b.output_tokens for b in batches)
    worst = sum(b.calls * b.max_output_tokens for b in batches)
    dollars: float | None = 0.0
    worst_dollars: float | None = 0.0
    for b in batches:
        p = price_for(b.model)
        if p is None:
            dollars = worst_dollars = None
            break
        dollars += (b.calls * b.input_tokens * p[0] + b.calls * b.output_tokens * p[1]) / 1e6
        worst_dollars += (b.calls * b.input_tokens * p[0] + b.calls * b.max_output_tokens * p[1]) / 1e6
    return Estimate(calls, tin, tout, worst, dollars, worst_dollars)


def report(batches: list[Batch]) -> str:
    est = estimate(batches)
    lines = [f"About to make {est.calls:,} real API calls:"]
    for b in batches:
        lines.append(f"  {b.label}: {b.calls:,} x {b.model} "
                     f"(~{b.input_tokens:,} in / ~{b.output_tokens:,} out per call)")
    lines.append(f"Estimated tokens: {est.input_tokens:,} in, {est.output_tokens:,} out "
                 f"(worst case {est.worst_output_tokens:,} out)")
    if est.dollars is None:
        lines.append("Estimated cost: price unknown for one of these models; see the token counts above.")
    else:
        lines.append(f"Estimated cost: ~${est.dollars:,.2f} (worst case ~${est.worst_dollars:,.2f}) "
                     "at list prices; your rates may differ.")

    spent = llm.usage_snapshot()
    in_left = config.MAX_INPUT_TOKENS - spent["input_tokens"]
    out_left = config.MAX_OUTPUT_TOKENS - spent["output_tokens"]
    lines.append(f"Spend caps: this uses {est.input_tokens / config.MAX_INPUT_TOKENS:.1%} of the global input cap "
                 f"and up to {est.worst_output_tokens / config.MAX_OUTPUT_TOKENS:.1%} of the output cap "
                 f"({in_left:,} input and {out_left:,} output tokens left).")
    if est.input_tokens > in_left:
        lines.append(f"WARNING: needs ~{est.input_tokens:,} input tokens but only {in_left:,} are left under "
                     "the global cap; the run will stop early. Raise DL_MAX_INPUT_TOKENS or use --limit.")
    if est.worst_output_tokens > out_left:
        lines.append(f"WARNING: could need up to {est.worst_output_tokens:,} output tokens but only {out_left:,} "
                     "are left under the global cap; the run may stop early.")
    return "\n".join(lines)


def confirm(batches: list[Batch], *, assume_yes: bool = False, ask: Callable[[str], str] = input,
            out: Callable[..., None] = print) -> bool:
    """Print the estimate and ask. Anything but y/yes is a no, and so is having no terminal to answer on."""
    out(report(batches))
    if assume_yes:
        out("--yes given: proceeding without asking.")
        return True
    calls = sum(b.calls for b in batches)
    try:
        answer = ask(f"Make {calls:,} real API calls? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")
