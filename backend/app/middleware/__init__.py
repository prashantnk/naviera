from fastapi import FastAPI

from app.middleware.logging import log_requests
from app.middleware.security_headers import add_security_headers


def register_middleware(app: FastAPI):
    """
    Registers all application middleware with the FastAPI app.
    """
    app.middleware("http")(log_requests)
    app.middleware("http")(add_security_headers)
