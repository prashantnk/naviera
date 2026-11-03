#!/usr/bin/env bash
# Runs once when the Codespace / Dev Container is created: installs dependencies and creates
# the local env files from their templates (fill them in, or use Codespaces secrets).
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring

echo "Installing backend dependencies (venv in backend/.venv; run 'poetry install --with e2e' if running UI E2E tests)"
poetry config virtualenvs.in-project true
(cd "${WORKSPACE_DIR}/backend" && poetry install)

echo "Installing frontend dependencies"
(cd "${WORKSPACE_DIR}/frontend" && npm ci)

[ -f "${WORKSPACE_DIR}/backend/.env" ] || cp "${WORKSPACE_DIR}/backend/.env.example" "${WORKSPACE_DIR}/backend/.env"
[ -f "${WORKSPACE_DIR}/frontend/.env.local" ] || cp "${WORKSPACE_DIR}/frontend/.env.example" "${WORKSPACE_DIR}/frontend/.env.local"

echo "Done. Start the stack with the VS Code task 'Naviera: Run Full Stack' (API :8000, web :3000)."
