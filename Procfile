market: cd backend && uv run python -m deadlang.marketplace.server
specialists: cd backend && MARKETPLACE_MODE=mcp DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group specialists
examiner: cd backend && MARKETPLACE_MODE=mcp DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group examiner-thorough
examiner-quick: cd backend && MARKETPLACE_MODE=mcp DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group examiner-quick
agents: cd backend && DISCOVERY=agntcy uv run python -m deadlang.agntcy.serve --group deliberators
api: cd backend && MARKETPLACE_MODE=mcp TRANSPORT=agntcy DISCOVERY=agntcy uv run uvicorn deadlang.api.server:app --port 8000
web: cd frontend && npm run dev
