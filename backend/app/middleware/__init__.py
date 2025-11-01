from app.middleware.logging import log_requests
from fastapi import FastAPI


def register_middleware(app: FastAPI):
    """
    Registers all application middleware with the FastAPI app.
    """
    app.middleware("http")(log_requests)
