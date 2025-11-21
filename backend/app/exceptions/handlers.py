import logging

from app.exceptions.definitions import TenantNotFoundException
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Get a logger for this module
logger = logging.getLogger(__name__)


async def tenant_not_found_exception_handler(
    request: Request, exc: TenantNotFoundException
):
    """
    Handles TenantNotFoundException and logs the relevant request details
    before returning a 404 response.
    """
    # Get context for logging from the request
    tenant_slug = request.headers.get("x-tenant-slug")
    auth_token = request.headers.get("authorization")

    # Log the critical details
    logger.warning(
        f"TenantNotFoundException: A 404 error was returned for an operation. "
        f"Requested Tenant Slug: '{tenant_slug}', "
        f"Path: {request.method} {request.url.path}, "
        f"Client IP: {request.client.host if request.client else 'unknown'}, "
        f"Auth Token Provided: {'yes' if auth_token else 'no'}"
    )

    return JSONResponse(
        status_code=404,
        content={"detail": "Tenant not found"},
    )


def register_exception_handlers(app: FastAPI):
    """
    Registers all custom exception handlers with the FastAPI app.
    """
    app.add_exception_handler(
        TenantNotFoundException, tenant_not_found_exception_handler  # type: ignore
    )
