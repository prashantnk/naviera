from app.core.logging import setup_logging

#  Run setup BEFORE creating the app
setup_logging()

import logfire
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlmodel.ext.asyncio.session import AsyncSession

# Import our application's high-level components
from app.api.v1.router import api_router as api_router_v1
from app.core.config import is_production, settings
from app.core.db import get_session
from app.exceptions.handlers import register_exception_handlers
from app.middleware import register_middleware
from app.repositories.health import database_is_reachable

API_DOCS_ENABLED = not is_production()
"""B-11 (A6-20): Swagger UI / ReDoc / openapi.json are local-only; prod exposes no API map."""
NOT_READY_STATUS_CODE = 503


def custom_generate_unique_id(route: APIRoute) -> str:
    """
    Forces OpenAPI to use the clean Python function name
    (e.g., 'list_shipments') instead of a verbose path-based name.
    """
    return f"{route.name}"


# Create the FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    generate_unique_id_function=custom_generate_unique_id,
    docs_url=settings.DOCS_ENDPOINT if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
)

# Instrument the app with Logfire
# (This sets up HTTP traffic monitoring)
logfire.instrument_fastapi(app, excluded_urls=["/health"])

# --- Register Components ---
# Register all custom exception handlers
register_exception_handlers(app)

# Register all application middleware
register_middleware(app)

# Register all v1 API routes
app.include_router(api_router_v1, prefix=settings.API_V1_STR)
# --- End Component Registration ---

# --- System Endpoints ---


@app.get("/", include_in_schema=False)
async def root():
    """Local: redirect to the API docs. Production: a plain liveness answer (no docs)."""
    if API_DOCS_ENABLED:
        return RedirectResponse(url=settings.DOCS_ENDPOINT)
    return {"status": "ok"}


@app.get("/health", tags=["System"])
async def health_check():
    """
    A simple health check endpoint to confirm the API is running.
    """
    return {"status": "ok"}


@app.get("/ready", tags=["System"])
async def readiness_check(session: AsyncSession = Depends(get_session)):
    """
    G-06: readiness = the process is up AND the database answers `SELECT 1`. Point uptime
    monitoring / alerts here (`/health` stays green while the database is down).
    """
    if await database_is_reachable(session):
        return {"status": "ok", "database": "ok"}
    return JSONResponse(
        status_code=NOT_READY_STATUS_CODE,
        content={"status": "unavailable", "database": "unreachable"},
    )
