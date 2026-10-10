#!/usr/bin/env bash
# One command for the whole AGNTCY stack.  ./scripts/stack.sh up | down | status | logs <name>
# Logs and pids live in .run/ (gitignored).
set -u
cd "$(dirname "$0")/.."
RUN=.run; mkdir -p $RUN
COMPOSE="docker compose -f infra/docker-compose.yaml"
B="cd backend &&"
A="MARKETPLACE_MODE=mcp DISCOVERY=agntcy"
SERVE="uv run python -m deadlang.agntcy.serve"

start() {  # name, command
  [ -f $RUN/$1.pid ] && kill -0 "$(cat $RUN/$1.pid)" 2>/dev/null && { echo "$1 already running"; return; }
  # own process group so `down` can kill the children (serve spawns one process per agent)
  nohup bash -c "set -m; exec bash -c '$2'" > $RUN/$1.log 2>&1 &
  echo $! > $RUN/$1.pid; echo "started $1"
}

wait_port() { for _ in $(seq 1 60); do nc -z localhost "$1" 2>/dev/null && return 0; sleep 2; done; echo "timeout waiting for port $1"; return 1; }

up() {
  open -a Docker 2>/dev/null; until docker info >/dev/null 2>&1; do sleep 2; done
  $COMPOSE up -d
  echo "waiting for the Directory..."
  for _ in $(seq 1 60); do [ "$(curl -s -o /dev/null -w %{http_code} http://localhost:8889/healthz/ready)" = 200 ] && break; sleep 3; done
  start market "$B uv run python -m deadlang.marketplace.server"
  wait_port 8100
  start specialists "$B $A $SERVE --group specialists"
  start examiner "$B $A $SERVE --group examiner-thorough"
  start examiner-quick "$B $A $SERVE --group examiner-quick"
  start agents "$B DISCOVERY=agntcy $SERVE --group deliberators"
  sleep 15   # let the agents connect to SLIM and register
  start api "$B $A TRANSPORT=agntcy uv run uvicorn deadlang.api.server:app --port 8000"
  start web "cd frontend && npm run dev -- -p 3100"
  wait_port 3100 && echo "Ready: http://localhost:3100   (logs: .run/<name>.log)"
}

down() {
  for f in $RUN/*.pid; do
    [ -f "$f" ] || continue
    pid=$(cat "$f"); pkill -TERM -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null; rm -f "$f"
  done
  pkill -f "deadlang.agntcy.serve" 2>/dev/null; pkill -f "deadlang.api.server" 2>/dev/null
  pkill -f "deadlang.marketplace.server" 2>/dev/null; pkill -f "next dev -p 3100" 2>/dev/null; pkill -f next-server 2>/dev/null
  $COMPOSE stop 2>&1 | tail -3
  echo stopped
}

status() {
  for p in 8100 8000 3100 46357 8888; do nc -z localhost $p 2>/dev/null && echo "port $p up" || echo "port $p DOWN"; done
  grep -h "Registered" $RUN/*.log 2>/dev/null
}

case "${1:-}" in
  up) up;; down) down;; status) status;; logs) tail -f "$RUN/${2:?name}.log";;
  *) echo "usage: $0 up|down|status|logs <name>"; exit 1;;
esac
