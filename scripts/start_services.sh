#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TRACE_HOST="${TRACE_HOST:-127.0.0.1}"
TRACE_PORT="${TRACE_PORT:-6006}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8080}"
UI_HOST="${UI_HOST:-127.0.0.1}"
UI_PORT="${UI_PORT:-5173}"
TRACE_MODE="${NL_SQL_TRACE_MODE:-redacted}"
DEFAULT_DB="data/spider/spider_data/database/concert_singer/concert_singer.sqlite"
LOG_DIR="${LOG_DIR:-.cache/services}"

SKIP_INSTALL=0
SKIP_TRACE=0
SKIP_API=0
SKIP_UI=0

usage() {
  cat <<'EOF'
Usage: scripts/start_services.sh [options]

Starts the local nl-sql-agent services:
  - Phoenix tracing server
  - FastAPI backend
  - Vite/CopilotKit streaming chat UI

Options:
  --skip-install     Do not run uv sync or npm install.
  --skip-trace       Do not start Phoenix.
  --skip-api         Do not start the FastAPI backend.
  --skip-ui          Do not start the Vite UI.
  --trace-mode MODE  Set NL_SQL_TRACE_MODE for started services. Default: redacted.
  -h, --help         Show this help.

Environment overrides:
  TRACE_HOST, TRACE_PORT, API_HOST, API_PORT, UI_HOST, UI_PORT, LOG_DIR
  OPENAI_API_KEY, NL_SQL_DEFAULT_DB_PATH, NL_SQL_TRACE_MODE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --skip-trace)
      SKIP_TRACE=1
      shift
      ;;
    --skip-api)
      SKIP_API=1
      shift
      ;;
    --skip-ui)
      SKIP_UI=1
      shift
      ;;
    --trace-mode)
      TRACE_MODE="${2:-}"
      if [[ -z "$TRACE_MODE" ]]; then
        echo "Missing value for --trace-mode." >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_command() {
  local command_name="$1"
  local install_hint="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    echo "$install_hint" >&2
    exit 1
  fi
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-40}"
  local delay_seconds="${4:-1}"

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name is ready at $url"
      return 0
    fi
    sleep "$delay_seconds"
  done

  echo "$name did not become ready at $url. Check logs in $LOG_DIR." >&2
  return 1
}

start_service() {
  local name="$1"
  shift
  local log_file="$LOG_DIR/$name.log"

  echo "Starting $name. Logs: $log_file"
  "$@" >"$log_file" 2>&1 &
  PIDS+=("$!")
  NAMES+=("$name")
}

cleanup() {
  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo
    echo "Stopping services..."
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" >/dev/null 2>&1 || true
      fi
    done
    wait || true
  fi
}

PIDS=()
NAMES=()
trap cleanup EXIT INT TERM

require_command uv "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
require_command curl "Install curl with your system package manager."

if [[ "$SKIP_UI" -eq 0 ]]; then
  require_command npm "Install Node.js and npm: https://nodejs.org/"
fi

mkdir -p "$LOG_DIR"

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Add OPENAI_API_KEY before making LLM-backed requests."
fi

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  echo "Syncing Python dependencies with uv..."
  uv sync

  if [[ "$SKIP_UI" -eq 0 ]]; then
    echo "Installing UI dependencies..."
    if [[ -f "ui/package-lock.json" ]]; then
      npm --prefix ui ci
    else
      npm --prefix ui install --no-package-lock
    fi
  fi
fi

if [[ ! -f "$DEFAULT_DB" ]]; then
  echo "Spider data is missing. Preparing data/spider..."
  uv run nl-sql data download-spider --output data/spider
fi

export NL_SQL_DEFAULT_DB_PATH="${NL_SQL_DEFAULT_DB_PATH:-$ROOT_DIR/$DEFAULT_DB}"
export PHOENIX_COLLECTOR_ENDPOINT="${PHOENIX_COLLECTOR_ENDPOINT:-http://$TRACE_HOST:$TRACE_PORT/v1/traces}"
export NL_SQL_TRACE_MODE="$TRACE_MODE"

if [[ "$SKIP_TRACE" -eq 0 ]]; then
  start_service phoenix uv run nl-sql trace-server --host "$TRACE_HOST" --port "$TRACE_PORT"
fi

if [[ "$SKIP_API" -eq 0 ]]; then
  start_service api uv run nl-sql web --host "$API_HOST" --port "$API_PORT"
fi

if [[ "$SKIP_UI" -eq 0 ]]; then
  start_service ui npm --prefix ui run dev -- --host "$UI_HOST" --port "$UI_PORT"
fi

echo
echo "Service URLs:"
if [[ "$SKIP_TRACE" -eq 0 ]]; then
  echo "  Phoenix: http://$TRACE_HOST:$TRACE_PORT"
fi
if [[ "$SKIP_API" -eq 0 ]]; then
  echo "  API:     http://$API_HOST:$API_PORT"
fi
if [[ "$SKIP_UI" -eq 0 ]]; then
  echo "  UI:      http://$UI_HOST:$UI_PORT  (CopilotKit streaming chat)"
fi
echo
echo "Default DB: $NL_SQL_DEFAULT_DB_PATH"
echo "Trace mode: $NL_SQL_TRACE_MODE"
echo "Press Ctrl+C to stop all started services."
echo

if [[ "$SKIP_TRACE" -eq 0 ]]; then
  wait_for_url "Phoenix" "http://$TRACE_HOST:$TRACE_PORT" 60 1 || true
fi
if [[ "$SKIP_API" -eq 0 ]]; then
  wait_for_url "API" "http://$API_HOST:$API_PORT/docs" 60 1 || true
fi
if [[ "$SKIP_UI" -eq 0 ]]; then
  wait_for_url "UI" "http://$UI_HOST:$UI_PORT" 60 1 || true
fi

wait
