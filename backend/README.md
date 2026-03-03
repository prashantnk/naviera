# Naviera Backend 🚢

This directory contains the FastAPI backend for the Naviera logistics platform. It is built with Python 3.11, SQLModel, and Alembic, connecting to a PostgreSQL database hosted on Supabase.

The application is designed to be multi-tenant, with data isolation enforced at the database level.

---

## 🚀 Development Environment

This project is configured with a fully automated development environment using **Dev Containers**.

**The recommended way to work on this project is to use GitHub Codespaces.**

When you open this repository in a Codespace, it will automatically:

1.  Build a container with the correct Python version and all necessary tools (Poetry, Starship, etc.).
2.  Install all Python dependencies by running `poetry install`.
3.  Configure your VS Code editor with the recommended extensions and settings.

You can start coding immediately without any manual setup.

---

## 💻 Local Development Setup

If you prefer to work on your local machine, follow these steps.

### 1. Prerequisites

-   Python 3.11
-   [Poetry](https://python-poetry.org/docs/#installation) for dependency management.

### 2. Initial Setup

All commands should be run from the `naviera/backend/` directory.

1.  **Create Your Environment File**:
    This application requires a `.env` file for configuration. Copy the example file to create your own local version.

    ```bash
    cp .env.example .env
    ```

2.  **Configure the Database URL**:
    Open the newly created `.env` file. You must set the `DATABASE_URL` to your **Supabase Connection Pooler string**. Using the pooler is required for compatibility.

    ```env
    # backend/.env
    DATABASE_URL=postgresql+asyncpg://postgres.[your-project-ref]:[YOUR-PASSWORD]@[aws-0-ap-south-1.pooler.supabase.com:5432/postgres]
    DB_ECHO_LOG=True # Optional: Set to True to see all SQL queries
    ```

3.  **Install Dependencies**:
    Poetry will create a virtual environment (`.venv`) and install all packages.

    ```bash
    poetry install
    ```

4.  **Apply Database Migrations**:
    This command connects to your database and creates all the necessary tables (`tenant`, `user`, etc.).

    ```bash
    poetry run alembic upgrade head
    ```

5.  **Seed the Database**:
    This script populates the database with initial data (e.g., the first tenant and owner). It is safe to run multiple times.
    ```bash
    poetry run seed
    ```

### 3. Running the Application

Once the setup is complete, start the FastAPI development server:

```bash
# For local development
poetry run uvicorn app.main:app --reload

# For Codespaces
poetry run uvicorn app.main:app --host 0.0.0.0 --reload
```

The API will be available at `http://127.0.0.1:8000`. The `--reload` flag automatically restarts the server when you save code changes.

---

## 🗃️ Database Migrations (Alembic)

Alembic manages all changes to our database schema.

### The Workflow

1.  **Make changes** to your model files in `app/models/`.
2.  **Register the Model:** If you created a *new* file (e.g. `app/models/new_feature.py`), you **must** import it into `alembic/env.py` before running autogenerate, or Alembic won't see your changes:
    ```python
    # backend/alembic/env.py
    from app.models import tenants, pickups, new_feature # <-- Add it here
    ```
3.  **Generate a new migration script** that captures these changes.
4.  **Review** the generated script for correctness (crucial for Enums and custom types).
5.  **Apply** the migration to the database.

### Common Commands

-   **Generate a new migration:**

    ```bash
    # Always include a descriptive message with -m
    poetry run alembic revision --autogenerate -m "Add last_login_at to user model"
    ```

    **Critical Checklist (Mandatory):** After generating, always open the new file in `alembic/versions/` and check for the following:

    *   **Missing SQLModel Imports:** Alembic often forgets to import SQLModel's custom string types. Ensure this exact line is at the top of your migration file:
        ```python
        import sqlmodel.sql.sqltypes
        ```
    *   **Dropping Enums (Crucial for Postgres):** If you delete a table that uses an Enum, or drop an Enum column, SQLAlchemy's autogenerator will NOT drop the Enum type from Postgres. You will get "Type already exists" errors if you ever try to recreate it. You must manually add a raw SQL drop execution in the `downgrade` function:
        ```python
        def downgrade() -> None:
            op.drop_table('my_table')
            # YOU MUST MANUALLY ADD THIS FOR ENUMS:
            op.execute("DROP TYPE IF EXISTS userrole;")
        ```

-   **Apply migrations:**

    ```bash
    # Applies all migrations up to the latest version
    poetry run alembic upgrade head
    ```

-   **Revert migrations:**

    ```bash
    # Revert the very last migration
    poetry run alembic downgrade -1

    # Revert all migrations (for a clean slate)
    poetry run alembic downgrade base
    ```

### Troubleshooting: The "Empty Migration" Problem

If you run `poetry run alembic revision --autogenerate` and it produces an empty script (with just `pass`), it means Alembic's history is out of sync with the database. This usually happens after a failed or deleted migration.

If you run `poetry run alembic current`, you should see the current revision number.

**The definitive fix is to manually reset the database state:**

1.  Go to the Supabase dashboard and use the **Table Editor** to **delete the `alembic_version` table**. Also, delete any other application tables (`tenant`, `user`) if they are in an incorrect state.
2.  Delete the incorrect/empty migration script file from your local `alembic/versions/` folder.
3.  Re-run the `alembic revision --autogenerate` command again. It will now correctly generate the script.


### 🚀 Production Deployment Quick Reference (Render)
* **Runtime & Commands:** Python 3 environment. Build Command: `pip install poetry && poetry install`. Start Command: `poetry run uvicorn app.main:app --host 0.0.0.0 --port $PORT` & we can use `poetry run uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log` if we don't want to log any requests from uvicorn.
* **Database Connection:** `DATABASE_URL` must use the Supabase Connection Pooler (Port `6543`), and special characters in the database password must be URL-encoded (e.g., `$` becomes `%24`). `DB_ECHO_LOG` must be `"False"`.
* **Telemetry (Logfire):** Auto-tracing is strictly limited to `["app.api", "app.services", "app.repositories"]`, and the `/health` endpoint is filtered from Uvicorn logs to prevent quota drain on the free tier.
