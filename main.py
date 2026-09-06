"""
GitManager — Multi-Project Upstream Sync Framework.

FastAPI web server with per-project background sync workers.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.config import Settings, setup_logger, get_abs_path, ensure_dir
from src.core import WorkerPool, RateLimitMiddleware
from src.routers import projects_router, auth_router, webhooks_router, system_router, set_pool

logger = setup_logger(Settings.LOG_DIR / "main.log", name="gitmanager.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    pool = WorkerPool()
    set_pool(pool)
    app.state.pool = pool

    logger.info("╔══════════════════════════════════════════════════════════════╗")
    logger.info("║     GitManager — Multi-Project Sync Framework  v2.0         ║")
    logger.info("╚══════════════════════════════════════════════════════════════╝")
    logger.info(f"  API: http://{Settings.API_HOST}:{Settings.API_PORT}")
    logger.info(f"  Data: {Settings.RAW_DATA_DIR}/")
    logger.info(f"  Logs: {Settings.LOG_DIR}")
    logger.info("")

    yield

    logger.info("🛑  Shutting down — stopping all workers …")
    pool.stop_all()
    logger.info("✅  All workers stopped. Goodbye.")


app = FastAPI(
    title="GitManager",
    version=Settings.VERSION,
    lifespan=lifespan,
)

# Security middleware — rate limit + scanner auto-ban
app.add_middleware(
    RateLimitMiddleware,
    max_requests=60,        # 60 requests per minute per IP
    window_seconds=60,
    ban_duration=3600,      # 1 hour ban for scanners
    scanner_threshold=2,    # 2 scanner probe hits = instant ban
)

# Mount API routers
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(webhooks_router)
app.include_router(system_router)

# Mount docs directory (usage guide)
ensure_dir("docs")
app.mount("/docs", StaticFiles(directory=get_abs_path("docs")), name="docs")

# Mount static files (frontend)
ensure_dir("static")
app.mount("/", StaticFiles(directory=get_abs_path("static"), html=True), name="static")


if __name__ == "__main__":
    import os
    import signal
    import subprocess
    import time

    import uvicorn

    def kill_port(port: int) -> None:
        """Gracefully stop any process on the given port, then force-kill if needed."""
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5,
            )
            pids = result.stdout.strip()
            if not pids:
                return
            my_pid = os.getpid()
            target_pids = [
                int(p.strip()) for p in pids.splitlines()
                if p.strip() and int(p.strip()) != my_pid
            ]
            if not target_pids:
                return

            # Phase 1: Graceful SIGTERM (allows lifespan shutdown)
            for pid in target_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info(f"Sent SIGTERM to PID {pid} on port {port}")
                except ProcessLookupError:
                    pass

            # Wait up to 5 seconds for graceful shutdown
            for _ in range(25):
                time.sleep(0.2)
                check = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True, text=True, timeout=3,
                )
                remaining = [
                    int(p.strip()) for p in check.stdout.strip().splitlines()
                    if p.strip() and int(p.strip()) != my_pid
                ]
                if not remaining:
                    logger.info(f"Port {port} is now free (graceful)")
                    return

            # Phase 2: Force-kill survivors
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGKILL)
                    logger.warning(f"Force-killed PID {pid} on port {port}")
                except ProcessLookupError:
                    pass

            time.sleep(0.5)
            logger.info(f"Port {port} cleanup complete")

        except FileNotFoundError:
            try:
                subprocess.run(
                    ["fuser", "-k", f"{port}/tcp"],
                    capture_output=True, timeout=5,
                )
                logger.info(f"Killed process on port {port} via fuser")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                logger.warning(f"Cannot auto-kill port {port}: lsof/fuser unavailable")
        except (subprocess.TimeoutExpired, ValueError) as e:
            logger.debug(f"Port cleanup interrupted: {e}")

    kill_port(Settings.API_PORT)

    uvicorn.run(
        "main:app",
        host=Settings.API_HOST,
        port=Settings.API_PORT,
        reload=Settings.is_development,
    )
