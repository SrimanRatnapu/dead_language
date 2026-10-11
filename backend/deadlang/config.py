"""Settings from the environment (and the repo-root .env). Defaults match .env.example.

Relative paths in DL_DATA_DIR / DL_USAGE_FILE resolve against backend/ (where the Procfile runs every
process), so all processes share one data dir and one usage file whatever their cwd.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(REPO_ROOT / ".env", override=False)


def _str(key: str, default: str) -> str:
    raw = os.getenv(key)
    if raw is None:
        return default
    value = raw.split(" #", 1)[0].strip()   # tolerate inline comments like `local   # local | mcp`
    return value or default


def _int(key: str, default: int) -> int:
    return int(_str(key, str(default)))


def _path(key: str, default: str) -> Path:
    p = Path(_str(key, default))
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


DATA_DIR: Path = _path("DL_DATA_DIR", "../data")
MAX_SPEND_USD: float = float(_str("DL_MAX_SPEND_USD", "20"))   # per UTC day, checked before each case
USAGE_FILE: Path = _path("DL_USAGE_FILE", ".usage.json")

MODEL_STRONG: str = _str("DL_MODEL_STRONG", "claude-sonnet-5-5")
MODEL_FAST: str = _str("DL_MODEL_FAST", "claude-haiku-4-5-20251001")

MAX_INPUT_TOKENS: int = _int("DL_MAX_INPUT_TOKENS", 6_000_000)
CASE_TIMEOUT_S: float = float(_str("DL_CASE_TIMEOUT_S", "420"))   # one case, all rounds; stalled agents fail the case instead of hanging
MAX_OUTPUT_TOKENS: int = _int("DL_MAX_OUTPUT_TOKENS", 600_000)
CASE_MAX_INPUT_TOKENS: int = _int("DL_CASE_MAX_INPUT_TOKENS", 300_000)
CASE_MAX_OUTPUT_TOKENS: int = _int("DL_CASE_MAX_OUTPUT_TOKENS", 30_000)

MARKETPLACE_MODE: str = _str("MARKETPLACE_MODE", "local")          # local | mcp
MARKETPLACE_MCP_URL: str = _str("MARKETPLACE_MCP_URL", "http://localhost:8100/mcp")
TRANSPORT: str = _str("TRANSPORT", "local")                        # local | agntcy
DISCOVERY: str = _str("DISCOVERY", "local")                        # local | agntcy
SLIM_ENDPOINT: str = _str("SLIM_ENDPOINT", "http://localhost:46357")
SLIM_SHARED_SECRET: str = _str("SLIM_SHARED_SECRET", "deadlang-shared-secret-change-me-32chars-min")
DIRECTORY_ADDRESS: str = _str("DIRECTORY_ADDRESS", "127.0.0.1:8888")
AGNTCY_BROADCAST: bool = _str("DL_AGNTCY_BROADCAST", "1").lower() not in ("0", "false", "no")   # 0: one call per agent
