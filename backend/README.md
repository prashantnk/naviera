# Naviera Backend 🚢

This directory contains the FastAPI backend for the Naviera logistics platform. It is built with Python 3.11, SQLModel, and Alembic, connecting to a PostgreSQL database hosted on Supabase.

The application is designed to be multi-tenant, with data isolation enforced at the database level.

---

## 🚀 Development Environment

This project is configured with a fully automated development environment using **Dev Containers**.

**The recommended way to work on this project is to use GitHub Codespaces.**

When you open this repository in a Codespace, it will automatically:

1. Build a container with the correct Python version and all necessary tools (Poetry, Starship, etc.).
2. Install all Python dependencies by running `poetry install`.
3. Configure your VS Code editor with the recommended extensions and settings.

You can start coding immediately without any manual setup.

---

## 💻 Local Development Setup

If you prefer to work on your local machine, follow these steps.

### 1. Prerequisites

- Python 3.11
- [Poetry](https://python-poetry.org/docs/#installation) for dependency management.

### 2. Initial Setup

All commands should be run from the `naviera/backend/` directory.

1. **Create Your Environment File**:
   This application requires a `.env` file for configuration. Copy the example file to create your own local version.

   ```bash
   cp .env.example .env
   ```

2. **Configure the Database URL**:
   Open the newly created `.env` file. You must set the `DATABASE_URL` to your **Supabase Connection Pooler string**. Using the pooler is required for compatibility.

   ```env
   # backend/.env
   DATABASE_URL=postgresql+asyncpg://postgres.[your-project-ref]:[YOUR-PASSWORD]@[aws-0-ap-south-1.pooler.supabase.com:5432/postgres]
   DB_ECHO_LOG=True # Optional: Set to True to see all SQL queries
   ```

3. **Install Dependencies**:
   Poetry will create a virtual environment (`.venv`) and install all packages.

   ```bash
   poetry install
   ```

4. **Apply Database Migrations**:
   This command connects to your database and creates all the necessary tables (`tenant`, `user`, etc.).

   ```bash
   poetry run alembic upgrade head
   ```

5. **Seed the Database**:
   This script populates the database with initial data (e.g., the first tenant and owner). It is safe to run multiple times.
   ```bash
   poetry run seed
   ```

### 3. Running the Application

Once the setup is complete, start the FastAPI development server:

```bash
poetry run uvicorn app.main:app --reload
```

The API will be available at [http://127.0.0.1](http://127.0.0.1):8000. The --reload flag automatically restarts the server when you save code changes.

---

## 🗃️ Database Migrations (Alembic)

Alembic manages all changes to our database schema.

### The Workflow

1.  **Make changes** to your model files in `app/models/`.
2.  **Generate a new migration script** that captures these changes.
3.  **Review** the generated script for correctness.
4.  **Apply** the migration to the database.

### Common Commands

- **Generate a new migration:**

  ```bash
  # Always include a descriptive message with -m
  poetry run alembic revision --autogenerate -m "Add last_login_at to user model"
  ```

  **Critical Step**: After generating, always open the new file in `alembic/versions/` to review it. You will likely need to **manually add `import sqlmodel`** at the top of the script.

- **Apply migrations:**

  ```bash
  # Applies all migrations up to the latest version
  poetry run alembic upgrade head
  ```

- **Revert migrations:**

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
