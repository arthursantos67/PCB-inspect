from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.analyses.router import router as analyses_router
from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.health import HealthReport, build_health_report
from app.ingestion.router import router as ingestion_router
from app.settings.router import router as settings_router
from app.users.router import router as users_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/schema",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(ingestion_router)
app.include_router(settings_router)
app.include_router(analyses_router)


@app.get("/health", response_model=HealthReport, tags=["support"])
async def health() -> HealthReport:
    return await build_health_report(settings)
