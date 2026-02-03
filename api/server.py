"""FastAPI server for Pocketwatcher configuration API."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.deps import init_clients, close_clients
from api.routes import triggers_router, settings_router, stats_router, backtest_router, metrics_router
from api.routes.backtest import start_background_refresh
from config.settings import settings


class APITokenMiddleware(BaseHTTPMiddleware):
    """Middleware to verify API token on mutating requests."""

    async def dispatch(self, request: Request, call_next):
        # Skip authentication if no token configured
        if not settings.api_token:
            return await call_next(request)

        # Only check token for mutating methods on /api routes
        if request.method in ("PUT", "POST", "DELETE") and request.url.path.startswith("/api"):
            token = request.headers.get("X-API-Token")
            if token != settings.api_token:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API token"},
                    headers={"WWW-Authenticate": "API-Key"},
                )

        return await call_next(request)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("api")


# Background task handle
_background_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _background_task

    logger.info("Starting Pocketwatcher Config API...")
    await init_clients()

    # Start background refresh for backtest cache
    _background_task = asyncio.create_task(start_background_refresh())
    logger.info("Background backtest refresh started")

    logger.info("API server ready")
    yield

    logger.info("Shutting down API server...")

    # Cancel background task
    if _background_task:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass

    await close_clients()


app = FastAPI(
    title="Pocketwatcher Config API",
    description="Live configuration dashboard API for Pocketwatcher",
    version="0.1.0",
    lifespan=lifespan,
)

# API Token authentication middleware (must be added before CORS)
app.add_middleware(APITokenMiddleware)

# CORS middleware - allow dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "http://127.0.0.1:3003",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(triggers_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(backtest_router, prefix="/api")
app.include_router(metrics_router)  # No prefix - /metrics is standard


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Pocketwatcher Config API",
        "version": "0.1.0",
        "docs": "/docs",
    }


async def run_server(host: Optional[str] = None, port: Optional[int] = None):
    """Run the API server."""
    bind_host = host or settings.api_host
    bind_port = port or settings.api_port

    logger.info(f"Starting API server on {bind_host}:{bind_port}")
    if settings.api_token:
        logger.info("API token authentication enabled")

    config = uvicorn.Config(
        app,
        host=bind_host,
        port=bind_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pocketwatcher Config API")
    parser.add_argument(
        "--host",
        default=None,
        help=f"Host to bind to (default: {settings.api_host} from API_HOST env)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Port to bind to (default: {settings.api_port} from API_PORT env)",
    )

    args = parser.parse_args()

    asyncio.run(run_server(host=args.host, port=args.port))
