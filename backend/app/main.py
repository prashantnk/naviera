from fastapi import FastAPI
from fastapi.responses import RedirectResponse

# Import our application's high-level components
from app.api.v1.router import api_router as api_router_v1
from app.core.config import settings
from app.exceptions.handlers import register_exception_handlers
from app.middleware import register_middleware

# Create the FastAPI app
app = FastAPI(title=settings.PROJECT_NAME)

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
    # Redirect the root URL to the /docs page
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
async def health_check():
    """
    A simple health check endpoint to confirm the API is running.
    """
    return {"status": "ok"}