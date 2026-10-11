# AGNTCY runbook (Mac)

How to run Watchdog with every agent as a real AGNTCY agent: A2A servers over SLIM, found through the AGNTCY Directory. Follow it top to bottom on a Mac. Every command is run from the repo root unless the step starts with `cd backend`.

None of this has been run against real SLIM yet; the code was tested on Windows without Docker, against fakes. Please write down what you see (step 10) so we know whether it works.

## What costs money

| Step | Model calls |
|---|---|
| 1–7 (setup, health checks, unit tests, integration tests, starting the servers) | **None.** The integration tests use stub agents. |
| 8 (one case over AGNTCY) | **Yes.** A case is a few Sonnet and Haiku calls through our spend-capped wrapper. The cost per case has not been measured yet; my rough guess is under $0.25. |
| 9 (kill test) | Yes, it runs one or two more cases. |

## 1. Install (once)

```bash
# Docker Desktop: https://www.docker.com/products/docker-desktop/  (start it; the whale icon must be steady)
brew install uv git
git clone https://github.com/SrimanRatnapu/dead_language.git
cd dead_language
cd backend && uv sync && cd ..          # installs Python 3.12 and every dependency, including agntcy-app-sdk 0.5.5
cp .env.example .env
```

Edit `.env` at the repo root:

- `ANTHROPIC_API_KEY=` your key. Steps 8 and 9 need it; nothing before them does.
- Leave `SLIM_SHARED_SECRET` as it is, or change it. Every process reads it from this one file, so it is always the same everywhere. It must be at least 32 characters.
- Leave `TRANSPORT=local` and `DISCOVERY=local` in the file. The commands below set the AGNTCY values on their own lines, so local mode keeps working for everyone else.

## 2. Start SLIM and the Directory

```bash
docker compose -f infra/docker-compose.yaml up -d
docker compose -f infra/docker-compose.yaml ps
```

You should see three containers: `slim-dataplane`, `dir-api-server` and a zot container. Wait until `dir-api-server` says `healthy`, which can take about a minute.

If Docker reports `no matching manifest for linux/arm64` on an Apple-silicon Mac, add `platform: linux/amd64` under that service in `infra/docker-compose.yaml` and run the command again.

## 3. Health checks

```bash
curl -s -o /dev/null -w "directory ready: %{http_code}\n" http://localhost:8889/healthz/ready   # expect 200
nc -z localhost 46357 && echo "SLIM is listening on 46357"
nc -z localhost 8888  && echo "Directory API is listening on 8888"
```

All three must succeed before going on.

## 4. Unit tests (no Docker needed, free)

```bash
cd backend
uv run pytest -m "not integration"
```

Everything should pass. On Windows only, prefix the command with `PYTHONUTF8=1`.

## 5. Integration tests (real SLIM and Directory, stub agents, free)

Stop any `serve` processes from step 6 first, because these tests serve the same agent names themselves.

```bash
cd backend
uv run pytest -m integration tests/test_agntcy_e2e.py -v
```

Expected: `4 passed`. If they are `skipped`, step 3 did not pass. The four tests are:

1. **point-to-point:** one A2A call over SLIM to an examiner.
2. **broadcast:** one message that reaches only the agents named in it, plus a direct repair call.
3. **Directory:** register two cards, then select by capability. The reason should end in "Found via the AGNTCY Directory."
4. **kill:** stop the thorough examiner's server. The next call fails, and discovery picks the quick examiner with the fallback sentence.

## 6. Start the agents (one terminal each)

```bash
# Terminal 1: the marketplace, shared by every process
cd backend && uv run python -m deadlang.marketplace.server

# Terminal 2: price checker, seller inventory, linked sellers, legal table, translator
cd backend && MARKETPLACE_MODE=mcp DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group specialists

# Terminal 3: thorough examiner (its own process so it can be killed)
cd backend && MARKETPLACE_MODE=mcp DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group examiner-thorough

# Terminal 4: quick examiner (the fallback)
cd backend && MARKETPLACE_MODE=mcp DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group examiner-quick

# Terminal 5: undercover, counsel, case_officer
cd backend && DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group deliberators
```

Each `serve` terminal should print:

```
Serving <names> over SLIM at http://localhost:46357.
Registered N AgentCard(s) in the AGNTCY Directory at 127.0.0.1:8888.
```

If SLIM is not up, `serve` gives up after 20 seconds with `Could not start ... Is SLIM up?` and exits.

To start everything at once instead, including the API and the UI, use `uvx honcho start`, which runs the `Procfile`.

## 7. Check that the cards are in the Directory (free)

```bash
cd backend && uv run python - <<'EOF'
import asyncio
from deadlang.agntcy.discovery import AgntcyDirectoryDiscovery
async def main():
    d = AgntcyDirectoryDiscovery()
    for cap in ["price_check", "seller_inventory", "linked_sellers", "legal_lookup", "material_exam", "translation"]:
        s = await d.select(cap)
        print(cap, "->", s.specialist_name if s else None, "|", s.why if s else "")
asyncio.run(main())
EOF
```

Every line should name an agent, and every reason should end in "Found via the AGNTCY Directory." A line ending without it means the Directory call failed and local cards were used.

## 8. Run one case over AGNTCY (costs money)

The demo cases are `L0266` (network), `L0181` (tagua), `L0241` (removed listing) and `L0172` (ambiguous).

```bash
cd backend
MARKETPLACE_MODE=mcp TRANSPORT=agntcy DISCOVERY=agntcy uv run python -m deadlang.deliberation.facilitator --listing L0181
```

It prints one line per event and ends with `OUTCOME: ... | stop: ...`. Check for these:

- `specialist.selected` lines whose `why` ends in "Found via the AGNTCY Directory."
- `round.started` with `active` listing the agents called that round, then `stance.posted` from those agents.
- No `cannot connect` errors.

To run it through the API instead, which is the same path the UI uses:

```bash
cd backend && MARKETPLACE_MODE=mcp TRANSPORT=agntcy DISCOVERY=agntcy uv run uvicorn deadlang.api.server:app --port 8000
# another terminal:
curl -s -X POST localhost:8000/api/cases -H 'content-type: application/json' -d '{"listing_id":"L0181"}'
curl -N localhost:8000/api/cases/C-0001/events
```

Token use is recorded in `backend/.usage.json`.

## 9. Kill test

**Real process kill.** This is the demo story.

1. Press Ctrl+C in Terminal 3 (the thorough examiner).
2. Run step 8 again.
3. Expect `specialist.failed` for `deadlang-examiner-thorough`, with error `timeout` or `cannot connect`. It should be followed by `specialist.selected` for `deadlang-examiner-quick`, with "deadlang-examiner-thorough did not respond, so chose deadlang-examiner-quick, which offers material_exam at a lower quality tier. Found via the AGNTCY Directory."
4. Note how long the failure takes. The thorough examiner gets at least 120 s before a call counts as timed out. If SLIM does not refuse the call quickly when nobody is listening, the case waits up to 120 s at this point. That is the most important thing to report.
5. Restart Terminal 3 to bring the examiner back.

**API kill switch.** This is instant and doesn't need a terminal; use it on stage if the real kill is slow.

```bash
curl -s -X POST localhost:8000/api/demo/kill-specialist -H 'content-type: application/json' -d '{"name":"deadlang-examiner-thorough"}'
```

The next case falls back right away. The kill expires after 60 s.

## 10. What to send back

Put these in `docs/agntcy-notes.md`:

- the result of step 5;
- the output of step 7;
- the last 10 lines of step 8;
- how long step 9 took to fall back;
- any errors.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Could not start ... SLIM did not answer within 20 s` | SLIM isn't running, or the wrong port is in use. Repeat steps 2–3. |
| Calls return `cannot connect ... did not answer within 10 s` | Same cause, seen from the facilitator side. |
| Every call times out but SLIM is up | `SLIM_SHARED_SECRET` differs between processes. Use the one `.env`, and remove any exported copy in your shell. |
| Reasons don't end in "Found via the AGNTCY Directory." | The Directory call failed, so local cards were used for 30 s. Check step 3. |
| Discovery picks an agent whose terminal is closed | Directory records stay after a process stops; there is no delete. The Facilitator marks it unhealthy on the first failed call and falls back. To start clean: `docker compose -f infra/docker-compose.yaml down` then `up -d`, then restart the `serve` terminals. |
| Rounds time out but direct calls work | Broadcast is misbehaving. Set `DL_AGNTCY_BROADCAST=0` on the API or facilitator command to send one call per agent instead. That is still over SLIM. |
| `listing_removed` or marketplace errors in a `serve` terminal | Terminal 1 (the marketplace) isn't running. The specialists read listings from it when `MARKETPLACE_MODE=mcp`. |

## How it fits together (for reference)

- **One server per agent:** `serve.py` starts one A2A server per agent, each on its own SLIM identity `default/default/<agent name>` and carrying its AgentCard from `cards.py`. Each `serve` process pushes its own cards to the Directory, so the Directory lists agents that have actually run.
- **Discovery:** `AgntcyDirectoryDiscovery` searches the Directory by the name of each agent that should offer a capability. It keeps exact name matches whose card tags carry that capability. It then picks with the same rules as local mode: the preferred tier first, healthy agents only, then the fastest.
- **Calls and broadcasts:** `AgntcyTransport` sends A2A `message/send` JSON-RPC over SLIM. A round is one broadcast, sent only to the agents named in that round; each agent takes its own turn out of it. The facilitator's own identity is `default/default/deadlang-facilitator-<pid>`.
- **Why the transport bypasses the SDK's A2A client:** in agntcy-app-sdk 0.5.5 that client has two problems. Its point-to-point call always uses SLIM's 6-second default timeout, and its broadcast drops replies already received when one agent times out. The envelope is the same one the SDK sends.
