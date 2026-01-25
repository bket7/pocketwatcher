"""API route modules."""

from .triggers import router as triggers_router
from .settings import router as settings_router
from .stats import router as stats_router
from .backtest import router as backtest_router

__all__ = ["triggers_router", "settings_router", "stats_router", "backtest_router"]
