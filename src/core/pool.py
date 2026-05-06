"""
Thread-based worker pool for managing per-project sync daemons.
Each project runs in its own daemon thread with an independent schedule.
"""

import threading

import schedule as schedule_lib

from src.config import Settings, setup_logger
from src.schema import ProjectMeta

from .watcher import ConfigWatcher

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.pool")


class _WorkerState:
    """Internal state for a single project worker."""

    __slots__ = ("project", "thread", "stop_event", "scheduler", "watcher")

    def __init__(
        self,
        project: ProjectMeta,
        thread: threading.Thread,
        stop_event: threading.Event,
        scheduler: schedule_lib.Scheduler,
        watcher: ConfigWatcher,
    ) -> None:
        self.project = project
        self.thread = thread
        self.stop_event = stop_event
        self.scheduler = scheduler
        self.watcher = watcher


class WorkerPool:
    """
    Manages daemon threads — one per tracked project.
    Thread-safe via a single lock guarding the workers dict.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: dict[str, _WorkerState] = {}

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self, project: ProjectMeta) -> bool:
        """
        Spawn a worker for the given project. Returns False if already running.
        """
        with self._lock:
            if project.id in self._workers:
                if self._workers[project.id].thread.is_alive():
                    logger.warning(f"Worker already running: {project.id}")
                    return False
                # Dead thread — clean up and restart
                del self._workers[project.id]

            stop_event = threading.Event()
            watcher = ConfigWatcher(project.id, project.path)
            sched = schedule_lib.Scheduler()

            thread = threading.Thread(
                target=self._worker_loop,
                args=(project.id, watcher, sched, stop_event),
                name=f"worker-{project.id}",
                daemon=True,
            )
            self._workers[project.id] = _WorkerState(
                project=project,
                thread=thread,
                stop_event=stop_event,
                scheduler=sched,
                watcher=watcher,
            )
            thread.start()
            logger.info(f"▶  Worker started: {project.id}")
            return True

    def stop(self, project_id: str) -> bool:
        """Signal a worker to stop. Returns False if not running."""
        with self._lock:
            state = self._workers.get(project_id)
            if not state:
                return False
            state.stop_event.set()
            logger.info(f"⏹  Worker stopping: {project_id}")
            return True

    def stop_all(self) -> None:
        """Signal all workers to stop."""
        with self._lock:
            for pid, state in self._workers.items():
                state.stop_event.set()
                logger.info(f"⏹  Worker stopping: {pid}")

    def is_running(self, project_id: str) -> bool:
        with self._lock:
            state = self._workers.get(project_id)
            return state is not None and state.thread.is_alive()

    def running_ids(self) -> list[str]:
        with self._lock:
            return [
                pid for pid, s in self._workers.items()
                if s.thread.is_alive()
            ]

    # ── Worker loop (runs in thread) ──────────────────────────────────────

    def _worker_loop(
        self,
        project_id: str,
        watcher: ConfigWatcher,
        sched: schedule_lib.Scheduler,
        stop_event: threading.Event,
    ) -> None:
        """Main loop for a single project worker thread."""
        # Import here to avoid circular imports
        from src.services.sync import sync_job

        logger.info(f"   [{project_id}] Worker loop started")

        # Register schedule
        self._register_schedule(sched, watcher, project_id)

        # Run initial sync
        try:
            sync_job(watcher)
        except Exception as exc:
            logger.error(f"   [{project_id}] Initial sync failed: {exc}")

        # Loop
        while not stop_event.is_set():
            stop_event.wait(timeout=watcher.poll_interval)
            if stop_event.is_set():
                break

            sched.run_pending()

            # Hot-reload check
            if watcher.has_changed():
                logger.info(f"   [{project_id}] Config change detected — reloading")
                watcher.reload()
                sched.clear()
                self._register_schedule(sched, watcher, project_id)
                try:
                    sync_job(watcher)
                except Exception as exc:
                    logger.error(f"   [{project_id}] Sync after reload failed: {exc}")

        logger.info(f"   [{project_id}] Worker loop stopped")

        # Clean up from workers dict
        with self._lock:
            self._workers.pop(project_id, None)

    @staticmethod
    def _register_schedule(
        sched: schedule_lib.Scheduler,
        watcher: ConfigWatcher,
        project_id: str,
    ) -> None:
        """Register sync_job on the per-project scheduler."""
        from src.services.sync import sync_job

        run_at, interval_minutes = watcher.sched_params()

        if run_at:
            sched.every().day.at(run_at).do(sync_job, watcher=watcher)
            logger.info(f"   [{project_id}] Scheduled: daily at {run_at}")
        else:
            sched.every(interval_minutes).minutes.do(sync_job, watcher=watcher)
            logger.info(f"   [{project_id}] Scheduled: every {interval_minutes}m")
