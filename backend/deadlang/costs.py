"""Cost estimates and the y/N prompt that scripts show before making real (paid) API calls.

Prices are list prices per million tokens as of 2026-10; they are an estimate, not a bill. The token estimate
is the same one llm.py uses for its budget check, so a run that fits here will not trip the caps by surprise.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import uuid4

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


# Output tokens per call as a multiple of the visible answer, because thinking (or progress text) counts as
# output and toward max_tokens. Calibrated on one real run: Opus 5.5 examiner calls averaged 310 output tokens
# against a 150 estimate. Models we have no run for use the default.
THINKING_OUTPUT_FACTOR = {"claude-opus-5": 2.1, "claude-fable": 2.1}
DEFAULT_THINKING_FACTOR = 1.5


def expected_output_tokens(model: str, visible: int) -> int:
    if not llm.thinks(model):
        return visible
    matches = [k for k in THINKING_OUTPUT_FACTOR if model.startswith(k)]
    factor = THINKING_OUTPUT_FACTOR[max(matches, key=len)] if matches else DEFAULT_THINKING_FACTOR
    return round(visible * factor)


def new_run_id() -> str:
    """Case ids that carry this are new for every run, so one run's usage cannot count against the next run's
    per-case caps."""
    return datetime.now().strftime("%m%d-%H%M%S") + "-" + uuid4().hex[:4]


# The API adds a hidden tool-use system prompt (about 300-350 tokens) and formats the tool definition on every
# tool call, none of which is in our prompt text. Measured on real examiner calls: 1,452 (Opus 5.5) and ~1,500
# (two earlier 80-call runs) input tokens per call, against 915 counted from prompt, schema and photo. So
# estimates add this to prompt + schema + photo.
TOOL_USE_OVERHEAD_TOKENS = llm.TOOL_USE_OVERHEAD_TOKENS


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
    output_tokens: int          # typical, thinking included (see expected_output_tokens)
    max_output_tokens: int      # the max_tokens the call sets
    calls_per_case: int | None = None    # calls that share one case id (and so one per-case cap)
    concurrency: int | None = None       # calls in flight at once, each reserving max_output_tokens
    cached_prefix_tokens: int = 0        # per call, the part of the prompt that is cached (llm.cached_prefix_tokens)


@dataclass(frozen=True)
class Estimate:
    calls: int
    input_tokens: int
    output_tokens: int
    worst_output_tokens: int
    dollars: float | None           # None if any model's price is unknown
    worst_dollars: float | None


def batch_input_tokens(b: Batch) -> int:
    """Input tokens as billed. With a cached prefix, the first call writes it (1.25x) and the rest read it (0.1x)."""
    if b.cached_prefix_tokens <= 0 or b.calls < 1:
        return b.calls * b.input_tokens
    prefix = min(b.cached_prefix_tokens, b.input_tokens)
    return b.calls * (b.input_tokens - prefix) + round(prefix * (llm.CACHE_WRITE_FACTOR + llm.CACHE_READ_FACTOR * (b.calls - 1)))


def call_cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float | None:
    """Dollars for one call or one usage row: cache writes at 1.25x the input price, reads at 0.1x. None: price unknown."""
    p = price_for(model)
    if p is None:
        return None
    billed_in = input_tokens + cache_write * llm.CACHE_WRITE_FACTOR + cache_read * llm.CACHE_READ_FACTOR
    return (billed_in * p[0] + output_tokens * p[1]) / 1e6


def usage_cost_usd(model: str, row: dict) -> float | None:
    return call_cost_usd(model, row.get("input_tokens", 0), row.get("output_tokens", 0),
                         row.get("cache_read_tokens", 0), row.get("cache_write_tokens", 0))


def estimate(batches: list[Batch]) -> Estimate:
    calls = sum(b.calls for b in batches)
    tin = sum(batch_input_tokens(b) for b in batches)
    tout = sum(b.calls * b.output_tokens for b in batches)
    worst = sum(b.calls * b.max_output_tokens for b in batches)
    dollars: float | None = 0.0
    worst_dollars: float | None = 0.0
    for b in batches:
        p = price_for(b.model)
        if p is None:
            dollars = worst_dollars = None
            break
        dollars += (batch_input_tokens(b) * p[0] + b.calls * b.output_tokens * p[1]) / 1e6
        worst_dollars += (batch_input_tokens(b) * p[0] + b.calls * b.max_output_tokens * p[1]) / 1e6
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
    in_left = config.MAX_INPUT_TOKENS - llm.effective_input(spent)
    out_left = config.MAX_OUTPUT_TOKENS - spent["output_tokens"]
    lines.append(f"Spend caps: this uses {est.input_tokens / config.MAX_INPUT_TOKENS:.1%} of the global input cap "
                 f"and ~{est.output_tokens / config.MAX_OUTPUT_TOKENS:.1%} of the output cap "
                 f"({est.worst_output_tokens / config.MAX_OUTPUT_TOKENS:.1%} if every call wrote max_tokens); "
                 f"{in_left:,} input and {out_left:,} output tokens left.")
    if est.input_tokens > in_left:
        lines.append(f"WARNING: needs ~{est.input_tokens:,} input tokens but only {in_left:,} are left under "
                     "the global cap; the run will stop early. Raise DL_MAX_INPUT_TOKENS or use --limit.")
    if est.output_tokens > out_left:
        lines.append(f"WARNING: expects ~{est.output_tokens:,} output tokens but only {out_left:,} are left under "
                     "the global cap; the run will stop early. Raise DL_MAX_OUTPUT_TOKENS or use --limit.")
    elif est.worst_output_tokens > out_left:
        lines.append(f"Note: the worst case (every call writes its full max_tokens, {est.worst_output_tokens:,}) "
                     "would pass the global output cap. The cap counts what calls actually write, so this is unlikely.")
    for b in batches:
        if b.cached_prefix_tokens > 0:
            lines.append(f"Prompt cache: {b.label} reuses ~{b.cached_prefix_tokens:,} tokens per call (one write at "
                         f"{llm.CACHE_WRITE_FACTOR}x, then reads at {llm.CACHE_READ_FACTOR}x), already counted above.")
    cap_in, cap_out = config.CASE_MAX_INPUT_TOKENS, config.CASE_MAX_OUTPUT_TOKENS
    for b in batches:
        if not (b.calls_per_case and b.concurrency):
            continue
        exp_in, exp_out = b.calls_per_case * b.input_tokens, b.calls_per_case * b.output_tokens
        peak_in, peak_out = b.concurrency * b.input_tokens, b.concurrency * b.max_output_tokens
        lines.append(f"Per case id ({b.label}): up to {b.calls_per_case} calls, ~{exp_in:,} in / ~{exp_out:,} out "
                     f"expected, plus {b.concurrency} calls in flight reserving up to {peak_in:,} in / {peak_out:,} out "
                     f"(per-case caps {cap_in:,} in / {cap_out:,} out).")
        if exp_out + peak_out > cap_out:
            lines.append(f"WARNING: one case would need ~{exp_out + peak_out:,} output tokens against the per-case output "
                         f"cap {cap_out:,}; the run would stop partway. Lower the concurrency, or raise DL_CASE_MAX_OUTPUT_TOKENS.")
        if exp_in + peak_in > cap_in:
            lines.append(f"WARNING: one case would need ~{exp_in + peak_in:,} input tokens against the per-case input "
                         f"cap {cap_in:,}; the run would stop partway. Raise DL_CASE_MAX_INPUT_TOKENS.")
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
