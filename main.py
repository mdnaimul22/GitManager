"""
GitManager — Multi-Project Upstream Sync Framework.

FastAPI web server with per-project background sync workers.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.config import Settings, setup_logger, get_abs_path, ensure_dir
from src.core import WorkerPool
from src.routers import projects_router, auth_router, set_pool

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

# Mount API routers
app.include_router(auth_router)
app.include_router(projects_router)

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
        """Force-kill any process on the given port and wait until it's free."""
        killed = False
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5,
            )
            pids = result.stdout.strip()
            if not pids:
                return
            my_pid = os.getpid()
            for pid_str in pids.splitlines():
                pid = int(pid_str.strip())
                if pid == my_pid:
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                    logger.info(f"Force-killed PID {pid} on port {port}")
                    killed = True
                except ProcessLookupError:
                    pass
        except FileNotFoundError:
            try:
                subprocess.run(
                    ["fuser", "-k", "-9", f"{port}/tcp"],
                    capture_output=True, timeout=5,
                )
                killed = True
                logger.info(f"Force-killed process on port {port} via fuser")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                logger.warning(f"Cannot auto-kill port {port}: lsof/fuser unavailable")
        except (subprocess.TimeoutExpired, ValueError):
            pass

        if killed:
            # Wait until the port is actually freed (max 3 seconds)
            for _ in range(15):
                time.sleep(0.2)
                check = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True, text=True, timeout=3,
                )
                remaining = [
                    p for p in check.stdout.strip().splitlines()
                    if p.strip() and int(p.strip()) != os.getpid()
                ]
                if not remaining:
                    logger.info(f"Port {port} is now free")
                    return
            logger.warning(f"Port {port} may still be occupied after kill")

    kill_port(Settings.API_PORT)

    uvicorn.run(
        "main:app",
        host=Settings.API_HOST,
        port=Settings.API_PORT,
        reload=Settings.is_development,
    )
