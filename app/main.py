import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.schemas.common import COMMON_ERROR_RESPONSES

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

# This finds your frontend folder safely
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

API_DESCRIPTION = "Common backend for the Employee360 web app."

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.API_VERSION,
        description=API_DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
    )

    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
            max_age=600,
        )

    register_exception_handlers(app)
    
    # 1. Connect the API (Login, Tasks, Projects, etc.)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX,
                       responses=COMMON_ERROR_RESPONSES)

    # 2. Serve the Frontend at /app
    if (FRONTEND_DIR / "index.html").exists():
        app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    # 3. Root URL redirects to the frontend app
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/app/")

    return app

app = create_app()