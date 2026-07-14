"""Thumbnail fetching with an on-disk cache.

Thumbnails come from https://archive.org/services/img/<identifier>. A small
thread pool bounds concurrency (part of the MAX_CONNECTIONS budget in
api.py), and the disk cache means re-running a search costs archive.org
nothing. Returns raw image bytes — turning them into a texture is the UI's
job, so this module stays GTK-free.

Cache integrity: writes go through a temp file + os.replace so a crash can
never leave a truncated entry (a corrupt cached thumbnail is permanent and
invisible otherwise — the UI's texture decode just fails silently forever).
Empty cache files are treated as misses, and invalidate() lets the UI drop
an entry its decoder rejected so the next fetch is clean.
"""

from __future__ import annotations

import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import cache_dir

THUMBNAIL_URL = "https://archive.org/services/img/{identifier}"

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def default_cache_dir() -> Path:
    return cache_dir() / "thumbnails"


class ThumbnailLoader:
    def __init__(self, session, cache_dir: Path | None = None, max_workers: int = 2):
        self.session = session
        self.cache_dir = cache_dir or default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        # Single-worker lane for "hero" images (the item page's one
        # thumbnail): list-row traffic can hold the main pool for seconds
        # on a fresh result set, and the page's own image shouldn't wait
        # in that line.
        self._priority_executor = ThreadPoolExecutor(max_workers=1)
        # Jobs are stamped with the generation current at submit time; a
        # worker picking up a stale-generation job drops it immediately.
        # Without this, thumbnails queued while browsing one result set
        # would still be downloaded after a new search, and the new
        # search's thumbnails would crawl through the queue behind them.
        self._generation = 0

    def fetch(self, identifier: str, callback, priority: bool = False):
        """Fetch a thumbnail asynchronously.

        ``callback(identifier, data_or_none)`` runs on a worker thread —
        UI callers must trampoline back to the main loop themselves.

        Returns the Future: list-row callers should ``.cancel()`` it when
        the requesting row leaves the screen (rows are recycled while
        scrolling, and every bind queues a job — without cancellation a
        long scroll leaves the visible rows' fetches queued behind
        hundreds of jobs for rows that no longer exist). Jobs pending at
        cancel_pending() time are likewise dropped without a callback.

        ``priority=True`` runs on the dedicated lane and is exempt from
        generation drops — it is an explicit one-off request (item page),
        not recyclable list traffic.
        """
        if priority:
            return self._priority_executor.submit(
                self._fetch, None, identifier, callback
            )
        return self._executor.submit(
            self._fetch, self._generation, identifier, callback
        )

    def cancel_pending(self) -> None:
        """Drop queued-but-not-started list fetches (e.g. on a new search)."""
        self._generation += 1

    def invalidate(self, identifier: str) -> None:
        """Drop a cached entry (e.g. bytes the UI's image decoder rejected,
        such as a file truncated by a crash before writes were atomic)."""
        try:
            self._cache_path(identifier).unlink(missing_ok=True)
        except OSError:
            pass

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._priority_executor.shutdown(wait=False, cancel_futures=True)

    def _cache_path(self, identifier: str) -> Path:
        return self.cache_dir / (_SAFE_CHARS.sub("_", identifier) + ".img")

    def _fetch(self, generation: int | None, identifier: str, callback) -> None:
        if generation is not None and generation != self._generation:
            return  # stale job from a superseded result set
        data: bytes | None = None
        try:
            path = self._cache_path(identifier)
            if path.exists():
                data = path.read_bytes() or None  # empty file: cache miss
            if data is None:
                url = THUMBNAIL_URL.format(identifier=identifier)
                response = self.session.get(url, timeout=20)
                if response.ok and response.content:
                    data = response.content
                    self._write_cache(path, data)
        except Exception:
            data = None
        callback(identifier, data)

    def _write_cache(self, path: Path, data: bytes) -> None:
        # Atomic: a crash mid-write must not leave a truncated entry.
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
