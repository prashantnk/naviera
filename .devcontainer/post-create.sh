#!/usr/bin/env bash
# .devcontainer/post-create.sh
# Runs once when the GitHub Codespace / Dev Container is created.
# Paths are derived from this script's location, so it works for any fork or folder name.

set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "🚢 Setting up Naviera in ${WORKSPACE_DIR}"

# --- 1. System CLI tools (Debian bookworm: works on amd64 + arm64) ---
echo "📦 Installing system packages"
sudo apt-get update
sudo apt-get install -y git-lfs bat bash-completion curl netcat-openbsd lsd

# --- 2. Backend (FastAPI via Poetry, venv inside backend/.venv for VS Code) ---
echo "🐍 Installing backend dependencies"
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
poetry config virtualenvs.in-project true
(cd "${WORKSPACE_DIR}/backend" && poetry install --with e2e)

# --- 3. Frontend (Next.js) ---
if [ -d "${WORKSPACE_DIR}/frontend" ]; then
  echo "⚛️  Installing frontend dependencies"
  (cd "${WORKSPACE_DIR}/frontend" && npm install)
fi

# --- 4. Environment files (populated from Codespaces secrets when present, else templates) ---
write_env_key() {
  local file="$1"
  local key="$2"
  local val="$3"
  python3 - "$file" "$key" "$val" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
key, val = sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}=")
replaced = False
out = []
for line in lines:
    if not replaced and pattern.match(line):
        out.append(f"{key}={val}")
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append(f"{key}={val}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

list_missing_keys() {
  local file="$1"
  shift
  python3 - "$file" "$@" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
required = sys.argv[2:]
values = {}
if path.exists():
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
missing = [k for k in required if not values.get(k) or "<" in values[k] or ">" in values[k]]
print(", ".join(missing))
PY
}

BACKEND_ENV="${WORKSPACE_DIR}/backend/.env"
if [ ! -f "${BACKEND_ENV}" ]; then
  cp "${WORKSPACE_DIR}/backend/.env.example" "${BACKEND_ENV}"
fi

# Cross-fill convenient defaults when one side is provided in Codespaces secrets
EFF_ALEMBIC_DATABASE_URL="${ALEMBIC_DATABASE_URL:-${DATABASE_URL:-}}"
EFF_SUPABASE_URL="${SUPABASE_URL:-${NEXT_PUBLIC_SUPABASE_URL:-}}"
EFF_SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-${NEXT_PUBLIC_SUPABASE_ANON_KEY:-}}"
EFF_JWT_ISSUER="${JWT_ISSUER:-${EFF_SUPABASE_URL:+${EFF_SUPABASE_URL%/}/auth/v1}}"

BACKEND_SET_COUNT=0
for pair in \
  "DATABASE_URL:${DATABASE_URL:-}" \
  "ALEMBIC_DATABASE_URL:${EFF_ALEMBIC_DATABASE_URL}" \
  "DB_ECHO_LOG:${DB_ECHO_LOG:-}" \
  "CONSOLE_LOG:${CONSOLE_LOG:-}" \
  "SECRET_KEY:${SECRET_KEY:-}" \
  "ALGORITHM:${ALGORITHM:-}" \
  "ACCESS_TOKEN_EXPIRE_MINUTES:${ACCESS_TOKEN_EXPIRE_MINUTES:-}" \
  "SUPABASE_URL:${EFF_SUPABASE_URL}" \
  "SUPABASE_ANON_KEY:${EFF_SUPABASE_ANON_KEY}" \
  "JWT_ISSUER:${EFF_JWT_ISSUER}" \
  "ENVIRONMENT:${ENVIRONMENT:-}" \
  "LOGFIRE_TOKEN:${LOGFIRE_TOKEN:-}" \
  "PROJECT_NAME:${PROJECT_NAME:-}" \
  "API_V1_STR:${API_V1_STR:-}" \
  "DOCS_ENDPOINT:${DOCS_ENDPOINT:-}" \
  "DELHIVERY_B2C_TOKEN:${DELHIVERY_B2C_TOKEN:-}" \
  "DELHIVERY_B2C_BASE_URL:${DELHIVERY_B2C_BASE_URL:-}" \
  "DELHIVERY_TENANT_ID:${DELHIVERY_TENANT_ID:-}" \
  "DELHIVERY_B2B_USERNAME:${DELHIVERY_B2B_USERNAME:-}" \
  "DELHIVERY_B2B_PASSWORD:${DELHIVERY_B2B_PASSWORD:-}" \
  "DELHIVERY_B2B_BASE_URL:${DELHIVERY_B2B_BASE_URL:-}"; do
  k="${pair%%:*}"
  v="${pair#*:}"
  if [ -n "${v}" ]; then
    write_env_key "${BACKEND_ENV}" "${k}" "${v}"
    BACKEND_SET_COUNT=$((BACKEND_SET_COUNT + 1))
  fi
done

BACKEND_MISSING="$(list_missing_keys "${BACKEND_ENV}" DATABASE_URL ALEMBIC_DATABASE_URL SECRET_KEY SUPABASE_URL SUPABASE_ANON_KEY JWT_ISSUER ENVIRONMENT)"
if [ -z "${BACKEND_MISSING}" ]; then
  echo "✅ backend/.env is ready (${BACKEND_SET_COUNT} key(s) applied from environment secrets)."
else
  echo "⚠️  backend/.env copied from backend/.env.example — fill in or set Codespaces secrets for: ${BACKEND_MISSING}"
fi

FRONTEND_ENV="${WORKSPACE_DIR}/frontend/.env.local"
if [ ! -f "${FRONTEND_ENV}" ]; then
  cp "${WORKSPACE_DIR}/frontend/.env.example" "${FRONTEND_ENV}"
fi

FRONTEND_SET_COUNT=0
for pair in \
  "NEXT_PUBLIC_SUPABASE_URL:${NEXT_PUBLIC_SUPABASE_URL:-${SUPABASE_URL:-}}" \
  "NEXT_PUBLIC_SUPABASE_ANON_KEY:${NEXT_PUBLIC_SUPABASE_ANON_KEY:-${SUPABASE_ANON_KEY:-}}" \
  "BACKEND_API_URL:${BACKEND_API_URL:-}" \
  "REVALIDATION_SECRET:${REVALIDATION_SECRET:-}"; do
  k="${pair%%:*}"
  v="${pair#*:}"
  if [ -n "${v}" ]; then
    write_env_key "${FRONTEND_ENV}" "${k}" "${v}"
    FRONTEND_SET_COUNT=$((FRONTEND_SET_COUNT + 1))
  fi
done

FRONTEND_MISSING="$(list_missing_keys "${FRONTEND_ENV}" NEXT_PUBLIC_SUPABASE_URL NEXT_PUBLIC_SUPABASE_ANON_KEY REVALIDATION_SECRET)"
if [ -z "${FRONTEND_MISSING}" ]; then
  echo "✅ frontend/.env.local is ready (${FRONTEND_SET_COUNT} key(s) applied from environment secrets)."
else
  echo "⚠️  frontend/.env.local copied from frontend/.env.example — fill in or set Codespaces secrets for: ${FRONTEND_MISSING}"
fi

# --- 5. Shell aliases & helpers (idempotent, generic) ---
BASHRC="${HOME}/.bashrc"
MARKER="# --- Naviera Shell Enhancements & Aliases ---"
if ! grep -qF "${MARKER}" "${BASHRC}"; then
  echo "🐚 Adding shell aliases to ${BASHRC}"
  {
    echo ""
    echo "${MARKER}"
    echo "export NAVIERA_DIR=\"${WORKSPACE_DIR}\""
    cat <<'EOF'
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
if [ -f /etc/bash_completion ]; then . /etc/bash_completion; fi
alias reload="source ~/.bashrc && echo 'Bash configuration reloaded!'"
alias run-backend="cd \"$NAVIERA_DIR/backend\" && poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app"
alias run-frontend="cd \"$NAVIERA_DIR/frontend\" && npm run dev"
alias ls='lsd -l --icon=auto'
alias ll='lsd -al --icon=auto'
alias cat='batcat'
EOF
  } >> "${BASHRC}"
fi

echo "✅ Setup complete. Open a new terminal, then use the VS Code task 'Naviera: Run Full Stack' (or run-backend / run-frontend)."
