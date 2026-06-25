#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/start-full-app.sh

Starts the local treasury stack:
  - Postgres in Docker, when DATABASE_URL points at localhost
  - FastAPI backend on http://localhost:8000
  - Vite frontend on http://localhost:5173
  - Firefly bridge on http://localhost:4747

Useful environment switches:
  START_DB=0             skip Docker Postgres
  REQUIRE_DB=1           fail instead of falling back when DB cannot start
  START_BRIDGE=0         skip the local Firefly bridge
  INSTALL_DEPS=0         skip npm/pip dependency bootstrap
  API_VENV_DIR=path      override the API virtualenv location
  API_PORT=8000          backend port
  WEB_PORT=5173          frontend port
  BRIDGE_PORT=4747       bridge port
  STOP_DB_ON_EXIT=1      stop the Docker Postgres container on Ctrl+C

Examples:
  scripts/start-full-app.sh
  START_BRIDGE=0 scripts/start-full-app.sh
  API_PORT=8080 WEB_PORT=5174 scripts/start-full-app.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

log() {
  printf '[start] %s\n' "$*"
}

warn() {
  printf '[warn] %s\n' "$*" >&2
}

die() {
  printf '[error] %s\n' "$*" >&2
  exit 1
}

trim() {
  local value="$*"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_env_file() {
  local env_file="$1"

  if [[ ! -f "$env_file" ]]; then
    warn "No .env found at $env_file; using code defaults and session-only values."
    return 0
  fi

  log "Loading $env_file"

  local line key raw_value value trimmed_value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="$(trim "$line")"

    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == export\ * ]] && line="$(trim "${line#export }")"
    [[ "$line" == *=* ]] || continue

    key="$(trim "${line%%=*}")"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key+x}" ]] && continue

    raw_value="${line#*=}"
    trimmed_value="$(trim "$raw_value")"

    if [[ "$trimmed_value" == \"* ]]; then
      value="${trimmed_value#\"}"
      value="${value%%\"*}"
    elif [[ "$trimmed_value" == \'* ]]; then
      value="${trimmed_value#\'}"
      value="${value%%\'*}"
    else
      value="${raw_value%%[[:space:]]#*}"
      value="$(trim "$value")"
      [[ "$value" == \#* ]] && value=""
    fi

    export "$key=$value"
  done < "$env_file"
}

python_supported() {
  "$@" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 12) else 1)' >/dev/null 2>&1
}

python_version() {
  "$@" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'
}

python_tag() {
  "$@" -c 'import sys; print(f"py{sys.version_info.major}{sys.version_info.minor}")'
}

select_python() {
  PYTHON_CMD=()

  if [[ -n "${PYTHON:-}" ]]; then
    read -r -a PYTHON_CMD <<< "$PYTHON"
    command -v "${PYTHON_CMD[0]}" >/dev/null 2>&1 || die "PYTHON is set to '$PYTHON' but it is not executable."
    python_supported "${PYTHON_CMD[@]}" || die "PYTHON='$PYTHON' is not supported. Use Python 3.11 or 3.12 for the pinned API dependencies."
    return
  fi

  if command -v py >/dev/null 2>&1; then
    local py_version
    for py_version in -3.12 -3.11; do
      if python_supported py "$py_version"; then
        PYTHON_CMD=(py "$py_version")
        return
      fi
    done

    local py_list_line py_tag
    while IFS= read -r py_list_line; do
      if [[ "$py_list_line" =~ -V:([^[:space:]]*3\.1[12][^[:space:]]*) ]]; then
        py_tag="${BASH_REMATCH[1]}"
        if python_supported py "-V:$py_tag"; then
          PYTHON_CMD=(py "-V:$py_tag")
          return
        fi
      fi
    done < <(py -0p 2>/dev/null || true)
  fi

  if command -v uv >/dev/null 2>&1; then
    local uv_version uv_python
    for uv_version in 3.12 3.11; do
      if uv_python="$(uv python find "$uv_version" 2>/dev/null)" && [[ -n "$uv_python" ]]; then
        if python_supported "$uv_python"; then
          PYTHON_CMD=("$uv_python")
          return
        fi
      fi
    done
  fi

  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_supported "$candidate"; then
      PYTHON_CMD=("$candidate")
      return
    fi
  done

  die "Python 3.11 or 3.12 is required for the pinned API dependencies."
}

venv_python() {
  local venv_dir="$1"

  if [[ -x "$venv_dir/Scripts/python.exe" ]]; then
    printf '%s' "$venv_dir/Scripts/python.exe"
    return
  fi

  printf '%s' "$venv_dir/bin/python"
}

install_node_deps() {
  [[ "${INSTALL_DEPS:-1}" == "1" ]] || return 0

  command -v npm >/dev/null 2>&1 || die "Node 20+ and npm are required."

  if [[ -d "$ROOT_DIR/node_modules" ]]; then
    log "JS dependencies already installed."
    return 0
  fi

  log "Installing JS workspace dependencies..."
  (cd "$ROOT_DIR" && npm install)
}

install_api_deps() {
  [[ "${INSTALL_DEPS:-1}" == "1" ]] || return 0

  local api_venv_was_set="${API_VENV_DIR+x}"
  API_VENV_DIR="${API_VENV_DIR:-$ROOT_DIR/apps/api/.venv}"

  local api_python marker existing_version selected_tag

  if [[ -d "$API_VENV_DIR" ]]; then
    api_python="$(venv_python "$API_VENV_DIR")"
    if [[ -x "$api_python" ]] && ! python_supported "$api_python"; then
      existing_version="$(python_version "$api_python" 2>/dev/null || printf 'unknown')"
      if [[ -n "$api_venv_was_set" ]]; then
        die "API_VENV_DIR uses unsupported Python $existing_version. Use Python 3.11 or 3.12."
      fi

      select_python
      selected_tag="$(python_tag "${PYTHON_CMD[@]}")"
      warn "Existing apps/api/.venv uses Python $existing_version; using apps/api/.venv-$selected_tag for this run."
      API_VENV_DIR="$ROOT_DIR/apps/api/.venv-$selected_tag"
    fi
  fi

  if [[ ! -d "$API_VENV_DIR" ]]; then
    select_python
    log "Creating API virtualenv..."
    "${PYTHON_CMD[@]}" -m venv "$API_VENV_DIR"
  fi

  api_python="$(venv_python "$API_VENV_DIR")"
  [[ -x "$api_python" ]] || die "Virtualenv Python not found at $api_python"
  python_supported "$api_python" || die "API virtualenv uses unsupported Python $(python_version "$api_python"). Use Python 3.11 or 3.12."

  marker="$API_VENV_DIR/.deps-installed"
  if [[ ! -f "$marker" || "$ROOT_DIR/apps/api/requirements.txt" -nt "$marker" ]]; then
    log "Installing API Python dependencies..."
    "$api_python" -m pip install -r "$ROOT_DIR/apps/api/requirements.txt"
    touch "$marker"
  else
    log "API Python dependencies already installed."
  fi
}

parse_database_url() {
  DB_HOST="localhost"

  [[ -n "${DATABASE_URL:-}" ]] || return 0

  local re='^postgresql(\+asyncpg)?://([^:/]+):([^@]+)@([^:/]+):([0-9]+)/([^?]+)'
  if [[ "$DATABASE_URL" =~ $re ]]; then
    [[ -n "${POSTGRES_USER+x}" ]] || POSTGRES_USER="${BASH_REMATCH[2]}"
    [[ -n "${POSTGRES_PASSWORD+x}" ]] || POSTGRES_PASSWORD="${BASH_REMATCH[3]}"
    DB_HOST="${BASH_REMATCH[4]}"
    [[ -n "${POSTGRES_PORT+x}" ]] || POSTGRES_PORT="${BASH_REMATCH[5]}"
    [[ -n "${POSTGRES_DB+x}" ]] || POSTGRES_DB="${BASH_REMATCH[6]}"
  else
    warn "DATABASE_URL is set but could not be parsed for Docker bootstrap; leaving DB defaults in place."
  fi
}

start_database() {
  [[ "${START_DB:-1}" == "1" ]] || {
    log "Skipping Postgres because START_DB=0."
    return 0
  }

  parse_database_url

  POSTGRES_USER="${POSTGRES_USER:-postgres}"
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
  POSTGRES_DB="${POSTGRES_DB:-treasury}"
  POSTGRES_PORT="${POSTGRES_PORT:-5432}"
  DB_CONTAINER="${DB_CONTAINER:-treasury-postgres}"
  DB_VOLUME="${DB_VOLUME:-treasury-postgres-data}"

  if [[ -z "${DATABASE_URL:-}" ]]; then
    export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}"
  fi

  case "$DB_HOST" in
    localhost|127.0.0.1|"")
      ;;
    *)
      log "DATABASE_URL points at $DB_HOST; assuming an external Postgres is already available."
      return 0
      ;;
  esac

  if ! command -v docker >/dev/null 2>&1; then
    if [[ "${REQUIRE_DB:-0}" == "1" ]]; then
      die "Docker is required to start local Postgres, but docker was not found."
    fi
    warn "Docker not found; API will start and fall back to in-memory storage if it cannot reach Postgres."
    return 0
  fi

  if ! docker info >/dev/null 2>&1; then
    if [[ "${REQUIRE_DB:-0}" == "1" ]]; then
      die "Docker is installed but not running."
    fi
    warn "Docker is not running; API will start and fall back to in-memory storage if it cannot reach Postgres."
    return 0
  fi

  if docker ps --format '{{.Names}}' | grep -Fxq "$DB_CONTAINER"; then
    log "Postgres container '$DB_CONTAINER' is already running."
  elif docker ps -a --format '{{.Names}}' | grep -Fxq "$DB_CONTAINER"; then
    log "Starting existing Postgres container '$DB_CONTAINER'..."
    docker start "$DB_CONTAINER" >/dev/null
  else
    log "Creating Postgres container '$DB_CONTAINER' on localhost:$POSTGRES_PORT..."
    docker run \
      --name "$DB_CONTAINER" \
      -e "POSTGRES_USER=$POSTGRES_USER" \
      -e "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
      -e "POSTGRES_DB=$POSTGRES_DB" \
      -p "127.0.0.1:${POSTGRES_PORT}:5432" \
      -v "${DB_VOLUME}:/var/lib/postgresql/data" \
      -d postgres:16-alpine >/dev/null
    DB_STARTED_BY_SCRIPT=1
  fi

  log "Waiting for Postgres..."
  local attempt
  for attempt in {1..45}; do
    if docker exec "$DB_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      log "Postgres ready at localhost:$POSTGRES_PORT/$POSTGRES_DB."
      return 0
    fi
    sleep 1
  done

  if [[ "${REQUIRE_DB:-0}" == "1" ]]; then
    die "Postgres did not become ready in time."
  fi

  warn "Postgres did not become ready in time; API may fall back to in-memory storage."
}

ensure_firefly_keys() {
  [[ "${START_BRIDGE:-1}" == "1" ]] || return 0

  if [[ -n "${FIREFLY_DEVICE_PATH:-}" ]]; then
    [[ -n "${FIREFLY_PUBLIC_KEY:-}" ]] || die "FIREFLY_DEVICE_PATH is set, but FIREFLY_PUBLIC_KEY is missing."
    return 0
  fi

  local key_output line key value
  key_output="$(cd "$ROOT_DIR" && npm run --silent keygen --workspace apps/firefly-bridge)"

  while IFS='=' read -r key value; do
    case "$key" in
      FIREFLY_PUBLIC_KEY)
        export "$key=$value"
        ;;
    esac
  done <<< "$key_output"

  [[ -n "${FIREFLY_MOCK_PRIVATE_KEY:-}" && -n "${FIREFLY_PUBLIC_KEY:-}" ]] || die "Firefly key generation failed."

  warn "Using session-only Firefly mock keys. Add them to .env if you need stable approvals across restarts."
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local timeout="${3:-30}"

  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi

  local start_time=$SECONDS
  while (( SECONDS - start_time < timeout )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name ready: $url"
      return 0
    fi
    sleep 1
  done

  warn "$name did not answer within ${timeout}s: $url"
}

SERVICE_PIDS=()
DB_STARTED_BY_SCRIPT=0
CLEANING_UP=0

cleanup() {
  local status=$?

  [[ "$CLEANING_UP" == "0" ]] || exit "$status"
  CLEANING_UP=1
  trap - EXIT INT TERM

  if ((${#SERVICE_PIDS[@]})); then
    log "Stopping app services..."
    local pid
    for pid in "${SERVICE_PIDS[@]}"; do
      kill "$pid" >/dev/null 2>&1 || true
    done
    wait "${SERVICE_PIDS[@]}" >/dev/null 2>&1 || true
  fi

  if [[ "$DB_STARTED_BY_SCRIPT" == "1" && "${STOP_DB_ON_EXIT:-0}" == "1" ]]; then
    log "Stopping Postgres container '$DB_CONTAINER'..."
    docker stop "$DB_CONTAINER" >/dev/null 2>&1 || true
  fi

  exit "$status"
}

trap cleanup EXIT INT TERM

start_api() {
  local api_python
  API_VENV_DIR="${API_VENV_DIR:-$ROOT_DIR/apps/api/.venv}"
  api_python="$(venv_python "$API_VENV_DIR")"
  [[ -x "$api_python" ]] || die "API virtualenv is missing. Run with INSTALL_DEPS=1 or set API_VENV_DIR."
  python_supported "$api_python" || die "API virtualenv uses unsupported Python $(python_version "$api_python"). Use Python 3.11 or 3.12."

  log "Starting API on http://localhost:${API_PORT:-8000}..."
  (
    cd "$ROOT_DIR/apps/api"
    exec "$api_python" -m uvicorn app.main:app --reload --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
  ) &
  SERVICE_PIDS+=("$!")
}

start_web() {
  command -v npm >/dev/null 2>&1 || die "npm is required to start the frontend."

  log "Starting web on http://localhost:${WEB_PORT:-5173}..."
  (
    cd "$ROOT_DIR/apps/web"
    exec npm run dev -- --host "${WEB_HOST:-0.0.0.0}" --port "${WEB_PORT:-5173}"
  ) &
  SERVICE_PIDS+=("$!")
}

start_bridge() {
  [[ "${START_BRIDGE:-1}" == "1" ]] || {
    log "Skipping Firefly bridge because START_BRIDGE=0."
    return 0
  }

  command -v npm >/dev/null 2>&1 || die "npm is required to start the Firefly bridge."

  log "Starting Firefly bridge on http://localhost:${BRIDGE_PORT:-4747}..."
  (
    cd "$ROOT_DIR"
    exec npm run dev:bridge
  ) &
  SERVICE_PIDS+=("$!")
}

main() {
  cd "$ROOT_DIR"

  load_env_file "$ROOT_DIR/.env"

  export API_PORT="${API_PORT:-8000}"
  export WEB_PORT="${WEB_PORT:-5173}"
  export BRIDGE_PORT="${BRIDGE_PORT:-4747}"
  export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://localhost:$API_PORT}"
  export VITE_BRIDGE_BASE_URL="${VITE_BRIDGE_BASE_URL:-http://localhost:$BRIDGE_PORT}"

  install_node_deps
  install_api_deps
  start_database
  ensure_firefly_keys

  start_api
  start_web
  start_bridge

  log "Stack is starting. Press Ctrl+C to stop app services."
  wait_for_http "API" "http://localhost:$API_PORT/health" 45
  wait_for_http "Web" "http://localhost:$WEB_PORT" 45
  if [[ "${START_BRIDGE:-1}" == "1" ]]; then
    wait_for_http "Firefly bridge" "http://localhost:$BRIDGE_PORT/health" 45
  fi

  log "Local URLs:"
  log "  API:            http://localhost:$API_PORT/docs"
  log "  Web dashboard:  http://localhost:$WEB_PORT"
  if [[ "${START_BRIDGE:-1}" == "1" ]]; then
    log "  Firefly bridge: http://localhost:$BRIDGE_PORT/health"
  fi

  if help wait 2>&1 | grep -q -- '-n'; then
    wait -n "${SERVICE_PIDS[@]}"
  else
    wait "${SERVICE_PIDS[@]}"
  fi
}

main "$@"
