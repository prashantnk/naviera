# backend/app/middleware/logging.py
import logging
import time

from fastapi import Request

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔥 NEW: Define paths that should be completely silent
EXCLUDED_PATHS = {"/health"}


async def log_requests(request: Request, call_next):
    """
    Middleware to log incoming requests and their processing time.
    """
    path = request.url.path

    # 🔥 NEW: If the path is in our exclude list, just process it and return silently.
    if path in EXCLUDED_PATHS:
        return await call_next(request)

    # For all other routes, proceed with logging
    start_time = time.time()
    logger.info(f"Request: {request.method} {path}")

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    logger.info(f"Response: {response.status_code} (took {process_time:.2f}ms)")

    return response
