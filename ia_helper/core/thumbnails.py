"""Thumbnail fetching with an on-disk cache.

Thumbnails come from https://archive.org/services/img/<identifier>. A small
thread pool bounds concurrency (part of the MAX_CONNECTIONS budget in
api.py), and the disk cache means re-running a search costs archive.org
nothing. Returns raw image bytes — turning them into a texture is the UI's
job, so this module stays GTK-free.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

THUMBNAIL_URL = "https://archive.org/services/img/{identifier}"

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def default_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "ia-helper" / "thumbnails"


class ThumbnailLoader:
    def __init__(self, session, cache_dir: Path | None = None, max_workers: int = 2):
        self.session = session
        self.cache_dir = cache_dir or default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def fetch(self, identifier: str, callback) -> None:
        """Fetch a thumbnail asynchronously.

        ``callback(identifier, data_or_none)`` runs on a worker thread —
        UI callers must trampoline back to the main loop themselves.
        """
        self._executor.submit(self._fetch, identifier, callback)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _cache_path(self, identifier: str) -> Path:
        return self.cache_dir / (_SAFE_CHARS.sub("_", identifier) + ".img")

    def _fetch(self, identifier: str, callback) -> None:
        data: bytes | None = None
        try:
            path = self._cache_path(identifier)
            if path.exists():
                data = path.read_bytes()
            else:
                url = THUMBNAIL_URL.format(identifier=identifier)
                response = self.session.get(url, timeout=20)
                if response.ok and response.content:
                    data = response.content
                    path.write_bytes(data)
        except Exception:
            data = None
        callback(identifier, data)
