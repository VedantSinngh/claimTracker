"""
app/main.py
────────────
FastAPI application factory.
Registers all routers, exception handlers, middleware, and startup hooks.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, claims, exclusions, handbooks, analytics, reviews
from app.core.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ClaimTrackerError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run startup tasks; yield control to the app; run shutdown tasks."""
    logger.info("claimtracker_startup", env=settings.APP_ENV)
    # Ensure upload directory exists
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("claimtracker_shutdown")


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    application = FastAPI(
        title="ClaimTracker",
        description="AI-powered health insurance claims processing platform",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────
    @application.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": exc.message},
        )

    @application.exception_handler(AuthorizationError)
    async def authz_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": exc.message},
        )

    @application.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": exc.message},
        )

    @application.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": exc.message},
        )

    @application.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.message, "errors": exc.details},
        )

    @application.exception_handler(ClaimTrackerError)
    async def generic_handler(request: Request, exc: ClaimTrackerError) -> JSONResponse:
        logger.error("unhandled_app_error", error=exc.message, details=exc.details)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred."},
        )

    # ── Health check ──────────────────────────────────────────────
    @application.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "version": "1.0.0"}

    # ── Routers ───────────────────────────────────────────────────
    application.include_router(auth.router)
    application.include_router(claims.router)
    application.include_router(reviews.router)
    application.include_router(exclusions.router)
    application.include_router(handbooks.router)
    application.include_router(analytics.router)

    return application


app = create_app()
