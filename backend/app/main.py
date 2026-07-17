from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.router import router as alerts_router
from app.analyses.router import router as analyses_router
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.health import HealthReport, build_health_report
from app.datasets.router import router as dataset_exports_router
from app.db.session import get_db
from app.detections.router import router as detections_router
from app.events.sse import router as events_router
from app.ingestion.router import router as ingestion_router
from app.inspections.router import router as inspections_router
from app.reports.router import router as reports_router
from app.settings.models_router import router as models_router
from app.settings.router import router as settings_router
from app.stats.router import router as stats_router
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
app.include_router(inspections_router)
app.include_router(settings_router)
app.include_router(models_router)
app.include_router(analyses_router)
app.include_router(detections_router)
app.include_router(events_router)
app.include_router(stats_router)
app.include_router(chat_router)
app.include_router(reports_router)
app.include_router(dataset_exports_router)
app.include_router(alerts_router)


@app.get("/health", response_model=HealthReport, tags=["support"])
async def health(db: AsyncSession = Depends(get_db)) -> HealthReport:
    return await build_health_report(settings, db)
