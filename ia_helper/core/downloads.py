"""Download queue: bounded workers, resume, verification, persistence.

Design notes:
  - One DownloadTask per file. Files download to ``<dest>.part`` and are
    renamed into place only after the size and (when known) MD5 check out,
    so a partially fetched or corrupt file can never masquerade as done.
  - Resume uses HTTP Range from the existing ``.part`` size; the MD5 is
    computed incrementally, rehashing the partial file first.
  - The queue is persisted as JSON in the XDG state dir. Progress ticks are
    NOT persisted — on load, progress is recovered from ``.part`` sizes.
  - Listeners are invoked on worker threads. UI code must trampoline to its
    main loop (see ui/downloads_view.py); this module stays GTK-free.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .config import Config, state_dir
from .items import FileEntry

DOWNLOAD_URL = "https://archive.org/download/{identifier}/{name}"
CHUNK_SIZE = 256 * 1024
PROGRESS_INTERVAL = 0.25  # seconds between progress notifications per task


class DownloadState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED_STATES = {DownloadState.COMPLETED, DownloadState.CANCELLED}


# Characters NTFS forbids in file names (plus control chars). Sanitized on
# every platform so download layouts are identical across OSes.
_UNPORTABLE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
# Windows reserved device names (as a bare stem, any extension).
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)


def safe_relative_path(name: str) -> PurePosixPath:
    """Map an IA file name (may contain subdirectories) to a safe,
    portable relative path.

    Traversal and absolute paths are rejected; characters and names that
    are invalid on Windows are sanitized rather than rejected, so the
    original archive.org name still drives the download URL while the
    local file gets a portable spelling.
    """
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe file name: {name!r}")
    parts = []
    for part in path.parts:
        part = _UNPORTABLE_CHARS.sub("_", part).rstrip(" .")
        if not part:
            raise ValueError(f"unsafe file name: {name!r}")
        if part.split(".", 1)[0].upper() in _RESERVED_NAMES:
            part = "_" + part
        parts.append(part)
    return PurePosixPath(*parts)


@dataclass
class DownloadTask:
    identifier: str
    file_name: str
    dest: Path
    size: int = 0
    md5: str = ""
    # Human-readable item title, for grouping in the UI. Optional —
    # tasks persisted before it existed fall back to the identifier.
    item_title: str = ""
    # The bulk job that spawned this task ("" for manual downloads);
    # cancelling a bulk job cancels its unfinished tasks by this tag.
    bulk_id: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: DownloadState = DownloadState.QUEUED
    downloaded: int = 0
    error: str = ""
    speed_bps: float = 0.0

    def __post_init__(self):
        self._pause = threading.Event()
        self._cancel = threading.Event()

    @property
    def is_self_manifest(self) -> bool:
        """True for <identifier>_files.xml — the checksum manifest itself.

        Its listed md5/size are inherently stale (the file can't contain
        its own hash), so verification is skipped for it, matching the
        official ia client. Live-verified: the listed md5 never matches.
        """
        return self.file_name == f"{self.identifier}_files.xml"

    @property
    def part_path(self) -> Path:
        return self.dest.with_name(self.dest.name + ".part")

    @property
    def item_dir(self) -> Path:
        """The per-item download directory (file names may contain
        subdirectories, so this walks up the right number of levels)."""
        depth = len(PurePosixPath(self.file_name).parts)
        return self.dest.parents[depth - 1]

    @property
    def progress(self) -> float:
        if self.size <= 0:
            return 0.0
        return min(1.0, self.downloaded / self.size)

    @property
    def url(self) -> str:
        return DOWNLOAD_URL.format(
            identifier=quote(self.identifier, safe=""),
            name=quote(self.file_name, safe="/"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "identifier": self.identifier,
            "file_name": self.file_name,
            "dest": str(self.dest),
            "size": self.size,
            "md5": self.md5,
            "item_title": self.item_title,
            "bulk_id": self.bulk_id,
            "state": self.state.value,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "DownloadTask":
        task = cls(
            identifier=raw["identifier"],
            file_name=raw["file_name"],
            dest=Path(raw["dest"]),
            size=int(raw.get("size") or 0),
            md5=raw.get("md5", ""),
            item_title=raw.get("item_title", ""),
            bulk_id=raw.get("bulk_id", ""),
            id=raw.get("id") or uuid.uuid4().hex,
        )
        state = DownloadState(raw.get("state", "queued"))
        # A task that was mid-flight when the app closed goes back in line.
        task.state = DownloadState.QUEUED if state == DownloadState.RUNNING else state
        task.error = raw.get("error", "")
        if task.part_path.exists():
            task.downloaded = task.part_path.stat().st_size
        elif task.state == DownloadState.COMPLETED:
            task.downloaded = task.size
        return task


def verify_download(task: DownloadTask) -> tuple[bool, str]:
    """Re-check a completed file against its recorded size/MD5, reading it
    fresh from disk. Blocking — call from a worker thread.

    Independent of the download path itself: catches on-disk corruption
    or tampering after the fact, not just a bad transfer.
    """
    if not task.dest.exists():
        return False, "file is missing"
    actual_size = task.dest.stat().st_size
    if task.is_self_manifest:
        # Its listed size/md5 are inherently stale (see is_self_manifest),
        # same exemption as at download-finalize time.
        return True, f"present ({actual_size:,} bytes); manifest is exempt from verification"
    if task.size and actual_size != task.size:
        return False, f"size mismatch ({actual_size:,} bytes, expected {task.size:,})"
    if not task.md5:
        return True, f"size matches ({actual_size:,} bytes); no checksum to verify"
    digest = hashlib.md5()
    with task.dest.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
    if digest.hexdigest() != task.md5:
        return False, "checksum mismatch"
    return True, "checksum verified"


class RateLimiter:
    """Token bucket shared by every running download worker.

    One instance per DownloadManager, not per task — a single ceiling
    applies to the whole queue's combined throughput, matching the
    Preferences setting. ``rate_bytes_per_sec <= 0`` means unlimited, in
    which case ``consume()`` is a no-op. Sleeps happen in short slices so
    a paused/cancelled task's worker notices promptly rather than
    oversleeping mid-throttle.

    Bucket capacity is floored at CHUNK_SIZE, not just the rate: a single
    ``consume()`` call is always for one whole chunk (up to CHUNK_SIZE,
    per ``response.iter_content(CHUNK_SIZE)``), and capacity below that
    would mean ``self._tokens >= n`` could never become true for a rate
    configured below CHUNK_SIZE bytes/sec — live-verified to hang a
    worker forever, not just throttle it, before this floor was added.
    """

    _MAX_SLEEP = 0.25

    def __init__(self, rate_bytes_per_sec: int = 0):
        self._lock = threading.Lock()
        self._rate = max(0, rate_bytes_per_sec)
        self._capacity = max(self._rate, CHUNK_SIZE)
        self._tokens = float(self._capacity)
        self._last = time.monotonic()

    def set_rate(self, rate_bytes_per_sec: int) -> None:
        with self._lock:
            self._rate = max(0, rate_bytes_per_sec)
            self._capacity = max(self._rate, CHUNK_SIZE)
            self._tokens = float(self._capacity)
            self._last = time.monotonic()

    def consume(self, n: int, stop_check=None) -> None:
        """Block until ``n`` bytes are within the rate, or ``stop_check()``
        (checked once per short sleep slice) returns True — a paced chunk
        must never make a cancel/pause request wait out the full throttle
        before it's noticed."""
        while True:
            with self._lock:
                if self._rate <= 0:
                    return
                now = time.monotonic()
                self._tokens = min(
                    float(self._capacity), self._tokens + (now - self._last) * self._rate
                )
                self._last = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                wait = min((n - self._tokens) / self._rate, self._MAX_SLEEP)
            if stop_check is not None and stop_check():
                return
            time.sleep(wait)


class DownloadManager:
    """Owns the queue and its worker threads. Thread-safe public methods."""

    def __init__(self, session, config: Config, state_path: Path | None = None,
                 autostart: bool = True):
        self.session = session
        self.config = config
        self.state_path = state_path or (state_dir() / "queue.json")
        self.autostart = autostart
        self._lock = threading.RLock()
        self._tasks: list[DownloadTask] = []
        self._listeners: list = []
        self._structure_listeners: list = []
        self._shutdown = False
        self._rate_limiter = RateLimiter(config.bandwidth_limit_kbps * 1024)
        self._load()
        if autostart:
            self._maybe_start()

    # -- public API ------------------------------------------------------

    def add_listener(self, callback) -> None:
        """callback(task) fires on any task change, ON A WORKER THREAD."""
        self._listeners.append(callback)

    def tasks(self) -> list[DownloadTask]:
        with self._lock:
            return list(self._tasks)

    def enqueue(self, identifier: str, entries: list[FileEntry],
                item_title: str = "", bulk_id: str = "") -> list[DownloadTask]:
        created = []
        with self._lock:
            active_dests = {
                t.dest for t in self._tasks if t.state not in FINISHED_STATES
            }
            for entry in entries:
                if entry.private:
                    # Access-restricted file: the download endpoint would
                    # return 403. The UI never offers these, but enforce it
                    # here too so no code path can queue one.
                    continue
                try:
                    relative = safe_relative_path(entry.name)
                except ValueError:
                    continue  # skip hostile/unportable names, keep the batch
                dest = Path(self.config.download_dir) / identifier / relative
                if dest in active_dests:
                    continue  # already queued/running/paused
                task = DownloadTask(
                    identifier=identifier,
                    file_name=entry.name,
                    dest=dest,
                    size=entry.size,
                    md5=entry.md5,
                    item_title=item_title,
                    bulk_id=bulk_id,
                )
                if dest.exists() and (task.size == 0 or dest.stat().st_size == task.size):
                    task.state = DownloadState.COMPLETED
                    task.downloaded = task.size
                self._tasks.append(task)
                created.append(task)
        self._save()
        for task in created:
            self._notify(task)
        if self.autostart:
            self._maybe_start()
        return created

    def pause(self, task: DownloadTask) -> None:
        with self._lock:
            if task.state == DownloadState.RUNNING:
                task._pause.set()  # worker transitions the state
                return
            if task.state == DownloadState.QUEUED:
                task.state = DownloadState.PAUSED
        self._save()
        self._notify(task)

    def resume(self, task: DownloadTask) -> None:
        """Resume a paused task; also serves as retry for a failed one."""
        with self._lock:
            if task.state not in (DownloadState.PAUSED, DownloadState.FAILED):
                return
            task._pause.clear()
            task._cancel.clear()
            task.error = ""
            task.state = DownloadState.QUEUED
        self._save()
        self._notify(task)
        if self.autostart:
            self._maybe_start()

    def cancel(self, task: DownloadTask) -> None:
        with self._lock:
            if task.state in FINISHED_STATES:
                return
            if task.state == DownloadState.RUNNING:
                task._cancel.set()  # worker cleans up and transitions
                return
            task.state = DownloadState.CANCELLED
        task.part_path.unlink(missing_ok=True)
        self._save()
        self._notify(task)

    def clear_finished(self) -> None:
        with self._lock:
            self._tasks = [t for t in self._tasks if t.state not in FINISHED_STATES]
        self._save()
        self._notify_structure()

    def prune_finished(self, max_kept: int) -> None:
        """Drop the oldest finished tasks beyond ``max_kept``.

        Bulk downloads stream thousands of files through the queue; without
        pruning, the persisted queue (and the UI) grows unboundedly with
        completed history.
        """
        removed = False
        with self._lock:
            finished = [t for t in self._tasks if t.state in FINISHED_STATES]
            excess = len(finished) - max_kept
            if excess > 0:
                to_drop = {t.id for t in finished[:excess]}
                self._tasks = [t for t in self._tasks if t.id not in to_drop]
                removed = True
        if removed:
            self._save()
            self._notify_structure()

    def add_structure_listener(self, callback) -> None:
        """callback() fires (possibly on a worker thread) when tasks are
        REMOVED from the queue (clear/prune) — row-level listeners only
        ever hear about tasks that still exist."""
        self._structure_listeners.append(callback)

    def _notify_structure(self) -> None:
        for callback in self._structure_listeners:
            callback()

    def set_max_concurrent(self, value: int) -> None:
        with self._lock:
            self.config.max_concurrent_downloads = value
        if self.autostart:
            self._maybe_start()

    def set_bandwidth_limit(self, kbps: int) -> None:
        """``kbps`` <= 0 means unlimited. Applies to already-running
        transfers immediately, not just future ones."""
        kbps = max(0, kbps)
        with self._lock:
            self.config.bandwidth_limit_kbps = kbps
        self._rate_limiter.set_rate(kbps * 1024)

    def shutdown(self) -> None:
        """Ask running workers to stop and persist the queue."""
        self._shutdown = True
        with self._lock:
            for task in self._tasks:
                if task.state == DownloadState.RUNNING:
                    task._pause.set()
        self._save()

    # -- internals ---------------------------------------------------------

    def _notify(self, task: DownloadTask) -> None:
        for callback in self._listeners:
            callback(task)

    def _save(self) -> None:
        with self._lock:
            payload = [t.to_dict() for t in self._tasks]
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass  # persistence is best-effort; the queue still works in-memory

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        for raw in payload:
            try:
                self._tasks.append(DownloadTask.from_dict(raw))
            except (KeyError, ValueError):
                continue

    def _maybe_start(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            running = sum(1 for t in self._tasks if t.state == DownloadState.RUNNING)
            capacity = self.config.max_concurrent_downloads - running
            for task in self._tasks:
                if capacity <= 0:
                    break
                if task.state == DownloadState.QUEUED:
                    task.state = DownloadState.RUNNING
                    task._pause.clear()
                    task._cancel.clear()
                    threading.Thread(
                        target=self._run, args=(task,), daemon=True
                    ).start()
                    capacity -= 1

    def _finish(self, task: DownloadTask, state: DownloadState, error: str = "") -> None:
        with self._lock:
            task.state = state
            task.error = error
            task.speed_bps = 0.0
        self._save()
        self._notify(task)
        self._maybe_start()

    def _run(self, task: DownloadTask) -> None:  # noqa: C901 — one linear download pass
        try:
            self._notify(task)
            task.dest.parent.mkdir(parents=True, exist_ok=True)
            part = task.part_path

            digest = hashlib.md5()
            resume_from = 0
            if part.exists():
                # Rehash what we already have so verification stays valid.
                with part.open("rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        digest.update(chunk)
                        resume_from += len(chunk)
            task.downloaded = resume_from

            headers = {}
            if resume_from:
                headers["Range"] = f"bytes={resume_from}-"

            response = self.session.get(
                task.url, stream=True, headers=headers, timeout=30
            )

            if response.status_code == 416 and resume_from:
                # Nothing left to request; fall through to verification.
                pass
            elif resume_from and response.status_code == 200:
                # Server ignored the Range: start over from byte zero.
                digest = hashlib.md5()
                resume_from = 0
                task.downloaded = 0
                part.unlink(missing_ok=True)
                response.raise_for_status()
                self._stream_to(task, response, part, digest)
            else:
                response.raise_for_status()
                self._stream_to(task, response, part, digest)

            if task._cancel.is_set():
                part.unlink(missing_ok=True)
                self._finish(task, DownloadState.CANCELLED)
                return
            if task._pause.is_set():
                self._finish(task, DownloadState.PAUSED)
                return

            if not task.is_self_manifest:
                if task.size and part.stat().st_size != task.size:
                    part.unlink(missing_ok=True)
                    self._finish(
                        task, DownloadState.FAILED, "size mismatch after download"
                    )
                    return
                if task.md5 and digest.hexdigest() != task.md5:
                    part.unlink(missing_ok=True)
                    self._finish(
                        task, DownloadState.FAILED, "checksum verification failed"
                    )
                    return

            task.dest.unlink(missing_ok=True)
            part.rename(task.dest)
            task.downloaded = task.size or task.downloaded
            self._finish(task, DownloadState.COMPLETED)
        except Exception as exc:  # noqa: BLE001 — worker boundary: fail the task
            self._finish(task, DownloadState.FAILED, str(exc))

    def _stream_to(self, task, response, part: Path, digest) -> None:
        mode = "ab" if task.downloaded else "wb"
        last_notify = 0.0
        last_bytes = task.downloaded
        last_time = time.monotonic()
        with part.open(mode) as out:
            for chunk in response.iter_content(CHUNK_SIZE):
                if task._cancel.is_set() or task._pause.is_set() or self._shutdown:
                    return
                out.write(chunk)
                digest.update(chunk)
                self._rate_limiter.consume(
                    len(chunk),
                    stop_check=lambda: (
                        task._cancel.is_set() or task._pause.is_set() or self._shutdown
                    ),
                )
                task.downloaded += len(chunk)

                now = time.monotonic()
                if now - last_notify >= PROGRESS_INTERVAL:
                    elapsed = now - last_time
                    if elapsed > 0:
                        task.speed_bps = (task.downloaded - last_bytes) / elapsed
                    last_bytes = task.downloaded
                    last_time = now
                    last_notify = now
                    self._notify(task)
