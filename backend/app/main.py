# backend/app/main.py
from app.api.v1.router import api_router as api_router_v1
from app.core.config import settings
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(api_router_v1, prefix=settings.API_V1_STR)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url=settings.DOCS_ENDPOINT)
