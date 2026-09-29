import os
import time
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.api.ai_routes import router as ai_router
from app.api.routes import router as reports_router
from app.connectors.glpi_connector import GLPIConnector
from app.core.config import settings

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description="METRİKA - Belgenet GLPI Servis Masası ve Operasyonel Metrik Raporlama Platformu",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and Templates
base_dir = os.path.dirname(__file__)
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")

os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# Register API Routers
app.include_router(reports_router)
app.include_router(ai_router)

START_TIME = time.time()


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Serves the official METRİKA product favicon for browser tabs.
    """
    ico_path = os.path.join(static_dir, "favicon.ico")
    if os.path.exists(ico_path):
        return FileResponse(ico_path, media_type="image/x-icon")
    return FileResponse(os.path.join(static_dir, "favicon.svg"), media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """
    Renders the single-page responsive executive dashboard.
    """
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_title": settings.APP_TITLE,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )


@app.get("/health")
async def health_check():
    """
    Kubernetes Liveness and Readiness Probe.
    Checks connector status and system uptime.
    """
    connector = GLPIConnector()
    glpi_health = await connector.check_health()
    uptime_seconds = round(time.time() - START_TIME, 1)

    return {
        "status": "healthy",
        "app": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "uptime_seconds": uptime_seconds,
        "timestamp": datetime.now().isoformat(),
        "data_sources": {
            "glpi": glpi_health,
            "mock": {"status": "available"},
        },
    }
