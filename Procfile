market: cd backend && uv run python -m deadlang.marketplace.server
specialists: cd backend && uv run python -m deadlang.agntcy.serve --group specialists
examiner: cd backend && uv run python -m deadlang.agntcy.serve --group examiner-thorough
agents: cd backend && uv run python -m deadlang.agntcy.serve --group deliberators
api: cd backend && uv run uvicorn deadlang.api.server:app --port 8000
web: cd frontend && npm run dev
