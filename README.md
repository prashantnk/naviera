# Naviera Monorepo 🚢

Naviera is an enterprise-grade, multi-tenant logistics SaaS platform. It is built using an **Edge-Dynamic Monolith** architecture, serving multiple logistics companies (tenants) from a single deployment while maintaining strict data isolation.

## 🏗️ Architecture Stack

- **Frontend:** Next.js 15 (App Router), Tailwind CSS, Shadcn UI, React Hook Form.
- **Backend:** Python 3.11, FastAPI, SQLModel, Alembic.
- **Database:** PostgreSQL (hosted on Supabase) using `asyncpg`.
- **Auth:** Supabase Auth (JWTs, Magic Links, OAuth).

## ☁️ Cloud IDE Quickstart (Recommended)

This repository is pre-configured for instant development in the cloud. You do not need to install Python, Node, or Postgres locally.

- **GitHub Codespaces:** Open this repo in a Codespace. The `.devcontainer` will automatically install Node, Poetry, and all VS Code extensions.
- **Google Project IDX:** Open this repo in IDX. The `.idx/dev.nix` file will provision a NixOS container with all necessary system dependencies.

_Once your cloud environment starts, open two terminals:_

1. **Terminal 1:** `cd backend && poetry run uvicorn app.main:app --host 0.0.0.0 --reload`
2. **Terminal 2:** `cd frontend && npm run dev`

## 📂 Repository Structure

- `/backend` - The FastAPI Python application. See `backend/README.md` for database and API details.
- `/frontend` - The Next.js React application. See `frontend/README.md` for UI and API client sync details.

## 🧪 Testing

The backend contains a comprehensive automated Pytest suite that validates both B2C and B2B workflows, financial engines, and NDR status transitions.

**Note:** The tests run real integration requests against the local Fast API server.

1. Ensure the FastAPI server is running in a separate terminal:
   ```bash
   cd backend
   poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
2. Run the test suite:
   ```bash
   cd backend
   poetry run pytest
   ```
