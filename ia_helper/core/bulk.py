"""Bulk downloads: feed an entire query's items through the download queue.

Design constraints (this is the app's largest IA-citizenship surface):

  - **Self-pacing.** The feeder holds one item's metadata fetch in flight
    at a time and only feeds while the download queue has fewer than
    LOW_WATER unfinished tasks. Draining downloads wake it; a 12k-item
    collection therefore trickles through at exactly the speed downloads
    complete, and the queue file never balloons.
  - **Skip, don't 403.** Restricted items (scrape flag) are skipped
    outright; private files and DRM lending containers are excluded from
    each item, same policy as the item page.
  - **Idempotent resume.** Jobs persist their processed count, and the
    scrape order is stable, so resuming skips already-processed
    identifiers without re-fetching their metadata; files already on disk
    at the right size are skipped without even creating queue entries.
  - **No auto-resume across restarts.** A restart restores RUNNING jobs
    as PAUSED — a multi-terabyte mistake should need a human click to
    continue.

Listeners are invoked on the feeder thread; UI code must trampoline.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .config import state_dir
from .downloads import DownloadManager, FINISHED_STATES, safe_relative_path
from .items import ItemClient
from .scrape import MAX_BULK_ITEMS, ScrapeClient

# Feed more items only when unfinished queue entries drop below this.
LOW_WATER = 25
# Keep the persisted queue bounded while thousands of files stream through.
PRUNE_KEEP_FINISHED = 300
# Give up on a job after this many consecutive item failures (network is
# down or the query rots) rather than burning through the whole set.
MAX_CONSECUTIVE_FAILURES = 5


class BulkJobState(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


BULK_FINISHED_STATES = {
    BulkJobState.COMPLETED,
    BulkJobState.CANCELLED,
    BulkJobState.FAILED,
}


@dataclass
class BulkJob:
    query: str
    label: str
    original_only: bool = False
    total_items: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: BulkJobState = BulkJobState.PAUSED
    processed_items: int = 0
    enqueued_files: int = 0
    skipped_restricted: int = 0
    failed_items: int = 0
    error: str = ""

    @property
    def progress(self) -> float:
        if self.total_items <= 0:
            return 0.0
        return min(1.0, self.processed_items / self.total_items)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "label": self.label,
            "original_only": self.original_only,
            "total_items": self.total_items,
            "state": self.state.value,
            "processed_items": self.processed_items,
            "enqueued_files": self.enqueued_files,
            "skipped_restricted": self.skipped_restricted,
            "failed_items": self.failed_items,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "BulkJob":
        job = cls(
            query=raw["query"],
            label=raw.get("label") or raw["query"],
            original_only=bool(raw.get("original_only")),
            total_items=int(raw.get("total_items") or 0),
            id=raw.get("id") or uuid.uuid4().hex,
        )
        state = BulkJobState(raw.get("state", "paused"))
        # Restarts never auto-resume a bulk job.
        job.state = BulkJobState.PAUSED if state == BulkJobState.RUNNING else state
        job.processed_items = int(raw.get("processed_items") or 0)
        job.enqueued_files = int(raw.get("enqueued_files") or 0)
        job.skipped_restricted = int(raw.get("skipped_restricted") or 0)
        job.failed_items = int(raw.get("failed_items") or 0)
        job.error = raw.get("error", "")
        return job


class BulkManager:
    """Owns bulk jobs and the single feeder thread."""

    def __init__(self, scrape_client: ScrapeClient, item_client: ItemClient,
                 download_manager: DownloadManager, state_path: Path | None = None,
                 autostart: bool = True, low_water: int = LOW_WATER):
        self._scrape = scrape_client
        self._items = item_client
        self._downloads = download_manager
        self.state_path = state_path or (state_dir() / "bulk.json")
        self.low_water = low_water
        self._lock = threading.RLock()
        self._jobs: list[BulkJob] = []
        self._listeners: list = []
        self._wake = threading.Event()
        self._shutdown = False
        self._load()
        # Finished downloads free queue capacity: wake the feeder.
        download_manager.add_listener(lambda task: self._wake.set())
        if autostart:
            threading.Thread(target=self._feeder_loop, daemon=True).start()

    # -- public API ----------------------------------------------------------

    def add_listener(self, callback) -> None:
        """callback(job) fires on job changes, ON THE FEEDER THREAD."""
        self._listeners.append(callback)

    def jobs(self) -> list[BulkJob]:
        with self._lock:
            return list(self._jobs)

    def start(self, query: str, label: str, original_only: bool,
              total_items: int) -> BulkJob:
        job = BulkJob(
            query=query,
            label=label,
            original_only=original_only,
            total_items=total_items,
            state=BulkJobState.RUNNING,
        )
        with self._lock:
            self._jobs.append(job)
        self._save()
        self._notify(job)
        self._wake.set()
        return job

    def pause(self, job: BulkJob) -> None:
        self._set_state(job, BulkJobState.PAUSED, only_from=(BulkJobState.RUNNING,))

    def resume(self, job: BulkJob) -> None:
        self._set_state(
            job, BulkJobState.RUNNING,
            only_from=(BulkJobState.PAUSED, BulkJobState.FAILED),
        )
        self._wake.set()

    def cancel(self, job: BulkJob) -> None:
        if job.state not in BULK_FINISHED_STATES:
            self._set_state(job, BulkJobState.CANCELLED)

    def clear_finished(self) -> None:
        with self._lock:
            self._jobs = [j for j in self._jobs if j.state not in BULK_FINISHED_STATES]
        self._save()

    def shutdown(self) -> None:
        self._shutdown = True
        self._wake.set()
        self._save()

    # -- internals ----------------------------------------------------------

    def _set_state(self, job: BulkJob, state: BulkJobState,
                   only_from: tuple = ()) -> None:
        with self._lock:
            if only_from and job.state not in only_from:
                return
            job.state = state
            if state == BulkJobState.RUNNING:
                job.error = ""
        self._save()
        self._notify(job)

    def _notify(self, job: BulkJob) -> None:
        for callback in self._listeners:
            callback(job)

    def _save(self) -> None:
        with self._lock:
            payload = [j.to_dict() for j in self._jobs]
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        for raw in payload:
            try:
                self._jobs.append(BulkJob.from_dict(raw))
            except (KeyError, ValueError):
                continue

    def _next_running_job(self) -> BulkJob | None:
        with self._lock:
            for job in self._jobs:
                if job.state == BulkJobState.RUNNING:
                    return job
        return None

    def _unfinished_downloads(self) -> int:
        return sum(
            1 for t in self._downloads.tasks() if t.state not in FINISHED_STATES
        )

    def _feeder_loop(self) -> None:
        while not self._shutdown:
            job = self._next_running_job()
            if job is None:
                self._wake.wait(timeout=5)
                self._wake.clear()
                continue
            try:
                self._process_job(job)
            except Exception as exc:  # noqa: BLE001 — feeder must survive
                self._set_state(job, BulkJobState.FAILED)
                job.error = str(exc)
                self._notify(job)

    def _process_job(self, job: BulkJob) -> None:
        """Walk the job's query, feeding items until done or interrupted.

        Restart/resume: scrape order is stable, so the first
        ``processed_items`` identifiers are skipped without metadata
        fetches (a full re-walk costs only the scrape pages themselves).
        """
        to_skip = job.processed_items
        consecutive_failures = 0
        seen = 0

        for page in self._scrape.pages(job.query):
            for item in page:
                seen += 1
                if seen <= to_skip:
                    continue
                if self._interrupted(job):
                    return
                self._throttle(job)
                if self._interrupted(job):
                    return

                if item.access_restricted:
                    job.skipped_restricted += 1
                    job.processed_items += 1
                    self._after_item(job)
                    continue

                try:
                    self._feed_item(job, item.identifier)
                    consecutive_failures = 0
                except Exception as exc:  # noqa: BLE001 — skip bad items
                    job.failed_items += 1
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        job.error = f"stopped after repeated failures: {exc}"
                        self._set_state(job, BulkJobState.FAILED)
                        return
                job.processed_items += 1
                self._after_item(job)

        if not self._interrupted(job):
            self._set_state(job, BulkJobState.COMPLETED)

    def _feed_item(self, job: BulkJob, identifier: str) -> None:
        details = self._items.get_item(identifier)
        entries = []
        for entry in details.files:
            if entry.private or entry.drm:
                continue
            if job.original_only and not entry.is_original:
                continue
            try:
                relative = safe_relative_path(entry.name)
            except ValueError:
                continue
            # Already on disk at the right size: skip without creating a
            # queue entry (keeps resume re-walks quiet).
            dest = (Path(self._downloads.config.download_dir)
                    / identifier / relative)
            if entry.size and dest.exists() and dest.stat().st_size == entry.size:
                continue
            entries.append(entry)
        if entries:
            created = self._downloads.enqueue(
                identifier, entries, item_title=details.title
            )
            job.enqueued_files += len(created)

    def _throttle(self, job: BulkJob) -> None:
        """Block while the download queue is full enough already."""
        while (not self._shutdown
               and job.state == BulkJobState.RUNNING
               and self._unfinished_downloads() >= self.low_water):
            self._wake.wait(timeout=2)
            self._wake.clear()

    def _interrupted(self, job: BulkJob) -> bool:
        return self._shutdown or job.state != BulkJobState.RUNNING

    def _after_item(self, job: BulkJob) -> None:
        if job.processed_items % 10 == 0 or job.processed_items == job.total_items:
            self._save()
            self._downloads.prune_finished(PRUNE_KEEP_FINISHED)
        self._notify(job)
