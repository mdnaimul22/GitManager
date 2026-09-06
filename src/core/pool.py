"""
Thread-based worker pool for managing per-project sync daemons.
Each project runs in its own daemon thread with an independent schedule.
Supports instant sync triggers for webhooks and on-demand sync.
"""

import threading

import schedule as schedule_lib

from src.config import Settings, setup_logger
from src.schema import ProjectMeta

from .watcher import ConfigWatcher

logger = setup_logger(Settings.LOG_DIR / "core.log", name="gitmanager.core.pool")


class _WorkerState:
    """Internal state for a single project worker."""

    __slots__ = (
        "project",
        "thread",
        "stop_event",
        "wakeup_event",
        "sync_trigger",
        "sync_lock",
        "scheduler",
        "watcher",
    )

    def __init__(
        self,
        project: ProjectMeta,
        thread: threading.Thread,
        stop_event: threading.Event,
        wakeup_event: threading.Event,
        sync_trigger: threading.Event,
        sync_lock: threading.Lock,
        scheduler: schedule_lib.Scheduler,
        watcher: ConfigWatcher,
    ) -> None:
        self.project = project
        self.thread = thread
        self.stop_event = stop_event
        self.wakeup_event = wakeup_event
        self.sync_trigger = sync_trigger
        self.sync_lock = sync_lock
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
            wakeup_event = threading.Event()
            sync_trigger = threading.Event()
            sync_lock = threading.Lock()
            watcher = ConfigWatcher(project.id, project.path)
            sched = schedule_lib.Scheduler()

            thread = threading.Thread(
                target=self._worker_loop,
                args=(project.id, watcher, sched, stop_event, wakeup_event, sync_trigger, sync_lock),
                name=f"worker-{project.id}",
                daemon=True,
            )
            self._workers[project.id] = _WorkerState(
                project=project,
                thread=thread,
                stop_event=stop_event,
                wakeup_event=wakeup_event,
                sync_trigger=sync_trigger,
                sync_lock=sync_lock,
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
            state.wakeup_event.set()
            logger.info(f"⏹  Worker stopping: {project_id}")
            return True

    def stop_all(self) -> None:
        """Signal all workers to stop."""
        with self._lock:
            for pid, state in self._workers.items():
                state.stop_event.set()
                state.wakeup_event.set()
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

    def trigger_now(self, project_id: str) -> bool:
        """
        Trigger an immediate sync run for a project.
        If worker is running, wakes it up to sync immediately.
        If worker is not running, spawns an asynchronous one-off sync thread.
        """
        with self._lock:
            state = self._workers.get(project_id)
            if state and state.thread.is_alive():
                state.sync_trigger.set()
                state.wakeup_event.set()
                logger.info(f"⚡ Instant sync signaled for running worker: {project_id}")
                return True

        # Not running in active pool: execute one-off background sync
        from src.services.project import get_project
        proj = get_project(project_id)
        if not proj:
            return False

        def _one_off_runner():
            from src.services.sync import sync_job
            try:
                watcher = ConfigWatcher(project_id, proj.path)
                sync_job(watcher)
            except Exception as exc:
                logger.error(f"   [{project_id}] One-off instant sync failed: {exc}")

        t = threading.Thread(
            target=_one_off_runner,
            name=f"one-off-sync-{project_id}",
            daemon=True,
        )
        t.start()
        logger.info(f"⚡ One-off instant sync thread started: {project_id}")
        return True

    # ── Worker loop (runs in thread) ──────────────────────────────────────

    def _worker_loop(
        self,
        project_id: str,
        watcher: ConfigWatcher,
        sched: schedule_lib.Scheduler,
        stop_event: threading.Event,
        wakeup_event: threading.Event,
        sync_trigger: threading.Event,
        sync_lock: threading.Lock,
    ) -> None:
        """Main loop for a single project worker thread."""
        # Import here to avoid circular imports
        from src.services.sync import sync_job

        logger.info(f"   [{project_id}] Worker loop started")

        # Register schedule
        self._register_schedule(sched, watcher, project_id, sync_lock)

        # Run initial sync
        try:
            with sync_lock:
                sync_job(watcher)
        except Exception as exc:
            logger.error(f"   [{project_id}] Initial sync failed: {exc}")

        # Loop
        while not stop_event.is_set():
            wakeup_event.wait(timeout=watcher.poll_interval)
            wakeup_event.clear()
            if stop_event.is_set():
                break

            # If triggered via webhook / API, execute immediate sync
            if sync_trigger.is_set():
                sync_trigger.clear()
                logger.info(f"   [{project_id}] Running instant sync triggered by webhook/API")
                try:
                    with sync_lock:
                        sync_job(watcher)
                except Exception as exc:
                    logger.error(f"   [{project_id}] Instant sync failed: {exc}")

            # Hot-reload check — MUST run before scheduled tasks so
            # sync_job always uses the latest config from disk.
            if watcher.has_changed():
                logger.info(f"   [{project_id}] Config change detected — reloading")
                watcher.reload()
                sched.clear()
                self._register_schedule(sched, watcher, project_id, sync_lock)
                try:
                    with sync_lock:
                        sync_job(watcher)
                except Exception as exc:
                    logger.error(f"   [{project_id}] Sync after reload failed: {exc}")

            sched.run_pending()

        logger.info(f"   [{project_id}] Worker loop stopped")

        # Clean up from workers dict
        with self._lock:
            self._workers.pop(project_id, None)

    @staticmethod
    def _register_schedule(
        sched: schedule_lib.Scheduler,
        watcher: ConfigWatcher,
        project_id: str,
        sync_lock: threading.Lock,
    ) -> None:
        """Register sync_job on the per-project scheduler."""
        from src.services.sync import sync_job

        def _locked_sync():
            with sync_lock:
                sync_job(watcher)

        run_at, interval_minutes = watcher.sched_params()

        if run_at:
            sched.every().day.at(run_at).do(_locked_sync)
            logger.info(f"   [{project_id}] Scheduled: daily at {run_at}")
        else:
            sched.every(interval_minutes).minutes.do(_locked_sync)
            logger.info(f"   [{project_id}] Scheduled: every {interval_minutes}m")
