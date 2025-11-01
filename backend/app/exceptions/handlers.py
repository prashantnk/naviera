from app.exceptions.definitions import TenantNotFoundException
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


async def tenant_not_found_exception_handler(
    request: Request, exc: TenantNotFoundException
):
    """
    Handles TenantNotFoundException and returns a 404 response.
    """
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
