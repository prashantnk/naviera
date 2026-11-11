#!/usr/bin/env bash
# Manage the local Naviera development environment lifecycle and dependency CVE hygiene.
#
# Subcommands:
#   up [--frozen]  Upgrade (or install frozen) backend + frontend dependencies, purge download
#                  caches, and enforce zero vulnerabilities via pip-audit and npm audit.
#   audit          Run backend (pip-audit) and frontend (npm audit --audit-level=moderate) checks.
#   down           Remove backend/.venv, frontend/node_modules, frontend/.next, and package caches.
#   status         Show environment materialization state and installed core framework versions.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"

export PYTHON_KEYRING_BACKEND="${PYTHON_KEYRING_BACKEND:-keyring.backends.null.Keyring}"
export POETRY_VIRTUALENVS_IN_PROJECT=true
POETRY="${POETRY:-$(command -v poetry || echo "$HOME/.local/bin/poetry")}"

if ! command -v npm > /dev/null 2>&1; then
  NVM_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2> /dev/null | sort -V | tail -1 || true)"
  if [ -n "$NVM_BIN" ]; then
    export PATH="$NVM_BIN:$PATH"
  fi
fi

usage() {
  cat <<'EOF'
Usage: bash scripts/dev_env.sh <command> [options]

Commands:
  up [--frozen]  Upgrade backend & frontend to latest compatible releases (or install exact
                 lockfiles when --frozen is passed), purge package download caches, and run
                 pip-audit + npm audit --audit-level=moderate.
  audit          Run pip-audit (backend) and npm audit --audit-level=moderate (frontend).
  down           Remove backend/.venv, frontend/node_modules, frontend/.next, and local
                 Poetry/pip/npm download caches so zero installed packages remain on disk.
  status         Print whether .venv and node_modules are materialized and current versions
                 of fastapi, starlette, and next.
EOF
}

purge_caches() {
  if command -v npm > /dev/null 2>&1; then
    npm cache clean --force > /dev/null 2>&1 || true
  fi
  rm -rf \
    "$HOME/.cache/pypoetry/cache" \
    "$HOME/.cache/pypoetry/artifacts" \
    "$HOME/.cache/pip" \
    "$HOME/.npm/_cacache"
}

read_dist_version() {
  local pkg="$1"
  local meta
  meta="$(ls "$BACKEND_DIR"/.venv/lib/python*/site-packages/"${pkg}"-*.dist-info/METADATA 2> /dev/null | head -n 1 || true)"
  if [ -n "$meta" ] && [ -f "$meta" ]; then
    awk -F': ' '/^Version:/ {print $2; exit}' "$meta"
  else
    echo "not installed"
  fi
}

read_npm_version() {
  local pkg_json="$FRONTEND_DIR/node_modules/$1/package.json"
  if [ -f "$pkg_json" ]; then
    sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$pkg_json" | head -n 1
  else
    echo "not installed"
  fi
}

cmd_audit() {
  local rc=0
  if [ ! -d "$BACKEND_DIR/.venv" ]; then
    echo "[audit] ERROR: backend/.venv is not materialized. Run 'bash scripts/dev_env.sh up' first." >&2
    return 1
  fi
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "[audit] ERROR: frontend/node_modules is not materialized. Run 'bash scripts/dev_env.sh up' first." >&2
    return 1
  fi

  echo "[audit] Running backend CVE scan (poetry run pip-audit)..."
  if "$POETRY" --directory "$BACKEND_DIR" run pip-audit; then
    echo "[audit] Backend pip-audit: PASS (0 vulnerabilities)"
  else
    echo "[audit] ERROR: Backend pip-audit reported vulnerabilities!" >&2
    rc=1
  fi

  echo "[audit] Running frontend CVE scan (npm audit --audit-level=moderate)..."
  if (cd "$FRONTEND_DIR" && npm audit --audit-level=moderate); then
    echo "[audit] Frontend npm audit: PASS (0 moderate+ vulnerabilities)"
  else
    echo "[audit] ERROR: Frontend npm audit reported moderate+ vulnerabilities!" >&2
    rc=1
  fi

  purge_caches
  return "$rc"
}

cmd_up() {
  local frozen=0
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --frozen) frozen=1 ;;
      -h|--help) usage; return 0 ;;
      *) echo "Unknown option for 'up': $1" >&2; usage >&2; return 2 ;;
    esac
    shift
  done

  if [ "$frozen" -eq 1 ]; then
    echo "[up] Installing locked backend dependencies (poetry install --with dev,e2e)..."
    "$POETRY" --directory "$BACKEND_DIR" install --with dev,e2e
    echo "[up] Installing locked frontend dependencies (npm ci)..."
    (cd "$FRONTEND_DIR" && npm ci)
  else
    echo "[up] Upgrading backend dependencies to latest compatible versions..."
    "$POETRY" --directory "$BACKEND_DIR" update
    "$POETRY" --directory "$BACKEND_DIR" install --with dev,e2e
    echo "[up] Upgrading frontend dependencies to latest compatible versions..."
    (cd "$FRONTEND_DIR" && npm update && npm install)
  fi

  echo "[up] Purging Poetry, pip, and npm download caches..."
  purge_caches

  cmd_audit
  cmd_status
}

cmd_down() {
  if [ "$#" -gt 0 ]; then
    echo "Unknown option for 'down': $1" >&2
    usage >&2
    return 2
  fi
  echo "[down] Removing backend/.venv, frontend/node_modules, and frontend/.next..."
  rm -rf \
    "$BACKEND_DIR/.venv" \
    "$FRONTEND_DIR/node_modules" \
    "$FRONTEND_DIR/.next"
  echo "[down] Purging local Poetry, pip, and npm download caches..."
  purge_caches
  echo "[down] Teardown complete: 0 materialized packages or cached archives remain."
}

cmd_status() {
  if [ "$#" -gt 0 ]; then
    echo "Unknown option for 'status': $1" >&2
    usage >&2
    return 2
  fi
  local venv_state="absent"
  local node_state="absent"
  local next_build_state="absent"
  [ -d "$BACKEND_DIR/.venv" ] && venv_state="materialized"
  [ -d "$FRONTEND_DIR/node_modules" ] && node_state="materialized"
  [ -d "$FRONTEND_DIR/.next" ] && next_build_state="materialized"

  local fastapi_ver="not installed"
  local starlette_ver="not installed"
  local next_ver="not installed"
  if [ "$venv_state" = "materialized" ]; then
    fastapi_ver="$(read_dist_version fastapi)"
    starlette_ver="$(read_dist_version starlette)"
  fi
  if [ "$node_state" = "materialized" ]; then
    next_ver="$(read_npm_version next)"
  fi

  echo "Naviera Dev Environment Status:"
  echo "  backend/.venv:         $venv_state"
  echo "  frontend/node_modules: $node_state"
  echo "  frontend/.next:        $next_build_state"
  echo "  fastapi:               $fastapi_ver"
  echo "  starlette:             $starlette_ver"
  echo "  next:                  $next_ver"
}

SUBCOMMAND="${1:-}"
if [ -z "$SUBCOMMAND" ]; then
  usage >&2
  exit 2
fi
shift

case "$SUBCOMMAND" in
  up) cmd_up "$@" ;;
  audit)
    if [ "$#" -gt 0 ]; then
      echo "Unknown option for 'audit': $1" >&2
      usage >&2
      exit 2
    fi
    cmd_audit
    ;;
  down) cmd_down "$@" ;;
  status) cmd_status "$@" ;;
  -h|--help|help) usage ;;
  *) echo "Unknown subcommand: $SUBCOMMAND" >&2; usage >&2; exit 2 ;;
esac
