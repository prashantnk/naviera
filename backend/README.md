# Naviera Backend

FastAPI-based backend for the Naviera logistics platform.

## Run locally

```bash
poetry install
poetry run uvicorn app.main:app --reload
# For codespaces use below:
poetry run uvicorn app.main:app --host 0.0.0.0 --reload
App will be available at http://127.0.0.1:8000

