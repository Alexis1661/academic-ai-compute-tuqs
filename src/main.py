import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.adapters.inbound.errors import register_exception_handlers
from src.adapters.inbound.router import router
from src.adapters.inbound.schemas import RootResponse
from src.adapters.outbound.migrations import run_migrations
from src.config import settings

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.AUTO_MIGRATE:
        run_migrations(settings.DATABASE_URL)
        logger.info("database migrated to head")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.2.0",
    description="Token Usage & Quota Service (TUQS) - Module 8 of Academic AI Compute Fabric",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/v1/openapi.json"
)

app.include_router(router)
register_exception_handlers(app)


@app.get("/", tags=["Root"], response_model=RootResponse)
def root():
    return RootResponse(
        service=settings.APP_NAME,
        module="Module 8: Token Usage & Quota Service (TUQS)",
        version=app.version,
        documentation="/docs",
        health=f"{settings.API_V1_PREFIX}/health",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=True)
