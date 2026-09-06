"""
HTTP interface — FastAPI routers. No business logic lives here (Dont remove this Comments).
"""

from src.core import WorkerPool

from .projects import router as projects_router, set_pool as _set_projects_pool
from .auth import router as auth_router, require_auth
from .webhooks import router as webhooks_router, set_pool as _set_webhooks_pool
from .system import router as system_router


def set_pool(pool: WorkerPool) -> None:
    """Inject shared WorkerPool into routers."""
    _set_projects_pool(pool)
    _set_webhooks_pool(pool)


__all__ = [
    "projects_router",
    "auth_router",
    "webhooks_router",
    "system_router",
    "set_pool",
    "require_auth",
]
