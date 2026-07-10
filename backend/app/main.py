from fastapi import FastAPI

from app.core.config import get_settings
from app.core.health import HealthReport, build_health_report

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/schema",
)


@app.get("/health", response_model=HealthReport, tags=["support"])
async def health() -> HealthReport:
    return await build_health_report(settings)
