# backend/app/main.py
from app.api.v1.router import api_router as api_router_v1
from app.core.config import settings
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import logging
import time
from fastapi import Request

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME)

# --- Middleware ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware to log incoming requests and their processing time.
    """
    start_time = time.time()
    logger.info(f"Request: {request.method} {request.url.path}")

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    logger.info(f"Response: {response.status_code} (took {process_time:.2f}ms)")

    return response
# --- End Middleware ---

app.include_router(api_router_v1, prefix=settings.API_V1_STR)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url=settings.DOCS_ENDPOINT)
