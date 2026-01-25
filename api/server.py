"""FastAPI server for Pocketwatcher configuration API."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import init_clients, close_clients
from api.routes import triggers_router, settings_router, stats_router, backtest_router
from api.routes.backtest import start_background_refresh

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


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Pocketwatcher Config API",
        "version": "0.1.0",
        "docs": "/docs",
    }


async def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the API server."""
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pocketwatcher Config API")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind to (default: 8080)",
    )

    args = parser.parse_args()

    asyncio.run(run_server(host=args.host, port=args.port))
