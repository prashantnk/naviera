---
name: db-migration
description: Guides approval-first PostgreSQL schema migrations with Alembic, including mandatory raw SQL handling for PostgreSQL ENUM types and PgBouncer safety.
---

# Database Migration Skill (`db-migration`)

Use this skill whenever a task requires adding or altering SQLModel database tables, columns, indexes, constraints, or PostgreSQL `ENUM` types in `backend/app/models/` and `backend/alembic/`.

## 1. Approval-First Rule (Mandatory)

**STOP before executing `alembic revision` or `alembic upgrade`!**
Because local development and production share the Supabase Postgres environment, you **must** first present to the user:
1. The exact tables, columns, indexes, or `ENUM` values being added or altered.
2. Why the schema change is required (and why an existing JSONB column such as `pricing_breakdown` or `settings` is not sufficient).
3. The exact `upgrade()` and `downgrade()` SQL operations.
4. Any impact on existing rows (backfill defaults, `NULL` constraints, foreign key cascades).

Only run `alembic` commands after the user explicitly approves.

---

## 2. PostgreSQL `ENUM` Migration Rules (No Autogenerate)

Alembic's `--autogenerate` **does not** detect mutations to existing PostgreSQL `ENUM` types (such as `pickupstatus`, `serviceoption`, `userrole`, `productcategory`).

### Adding a New Value to an Existing PostgreSQL `ENUM`
Use `op.execute(...)` inside `upgrade()`:
```python
def upgrade() -> None:
    op.execute("ALTER TYPE serviceoption ADD VALUE IF NOT EXISTS 'DELHIVERY_B2B'")
```

### Creating a New PostgreSQL `ENUM` Column Safely
Create the enum type with `create_type=False` on the column after explicitly creating it via `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN null; END $$;`:
```python
def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE primelane_mode AS ENUM ('ROAD', 'AIR'); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    )
```

---

## 3. Step-by-Step Workflow

1. **Update SQLModel Entity:** Edit the model in `backend/app/models/*.py` and ensure it is imported in `backend/app/models/__init__.py` so Alembic's metadata registry sees it.
2. **Check Current Head:**
   ```bash
   cd backend
   poetry run alembic heads
   poetry run alembic current
   ```
3. **Create Revision File (After User Approval):**
   ```bash
   cd backend
   poetry run alembic revision -m "descriptive_snake_case_name"
   ```
4. **Inspect & Edit the Generated Migration (`backend/alembic/versions/<rev>_*.py`):**
   - Never drop unrelated tables, indexes, or constraints.
   - Ensure new non-nullable columns on populated tables either provide a `server_default` or perform a 3-step `nullable=True` $\rightarrow$ `UPDATE` backfill $\rightarrow$ `ALTER COLUMN ... SET NOT NULL`.
   - Keep all imports at the top of the file (PEP8).
5. **Apply Migration (After User Approval):**
   ```bash
   cd backend
   poetry run alembic upgrade head
   ```
6. **Regenerate Frontend OpenAPI Client (If API Schemas Changed):**
   ```bash
   cd frontend
   curl -o openapi.json http://localhost:8000/openapi.json
   npx openapi-typescript-codegen --input openapi.json --output ./src/api_client --client axios
   rm openapi.json
   npx tsc --noEmit
   ```
7. **Verify with Golden Smoke:**
   ```bash
   bash backend/scripts/run_golden.sh --quick
   ```
