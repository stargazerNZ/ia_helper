"""Thumbnail loader tests — fake session, real thread pool."""

import tempfile
import threading
import unittest
from pathlib import Path

from ia_helper.core.thumbnails import ThumbnailLoader


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.ok = True


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return FakeResponse(b"image-bytes")


class BlockingSession(FakeSession):
    """get() signals `started` and then blocks until `release` is set."""

    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def get(self, url, timeout=None):
        self.started.set()
        self.release.wait(timeout=5)
        return super().get(url, timeout)


class TestThumbnailLoader(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_fetch_and_disk_cache(self):
        session = FakeSession()
        loader = ThumbnailLoader(session, cache_dir=self.cache, max_workers=1)
        results = {}
        loader.fetch("item-a", lambda ident, data: results.update({ident: data}))
        loader._executor.shutdown(wait=True)
        self.assertEqual(results["item-a"], b"image-bytes")
        self.assertEqual(session.calls, 1)

        # Second loader, same cache dir: served from disk, no HTTP.
        loader2 = ThumbnailLoader(session, cache_dir=self.cache, max_workers=1)
        loader2.fetch("item-a", lambda ident, data: results.update({"again": data}))
        loader2._executor.shutdown(wait=True)
        self.assertEqual(results["again"], b"image-bytes")
        self.assertEqual(session.calls, 1)

    def test_cancel_pending_drops_queued_jobs(self):
        session = BlockingSession()
        loader = ThumbnailLoader(session, cache_dir=self.cache, max_workers=1)
        calls = []

        # First job occupies the single worker (blocked inside get()).
        loader.fetch("item-a", lambda ident, data: calls.append(ident))
        self.assertTrue(session.started.wait(timeout=5))

        # Second job is queued behind it, then superseded by a "new search".
        loader.fetch("item-b", lambda ident, data: calls.append(ident))
        loader.cancel_pending()

        session.release.set()
        loader._executor.shutdown(wait=True)

        # The in-flight job completes; the stale queued one is dropped
        # without a callback and without an HTTP request.
        self.assertEqual(calls, ["item-a"])
        self.assertEqual(session.calls, 1)

    def test_cancelled_future_never_fetches(self):
        session = BlockingSession()
        loader = ThumbnailLoader(session, cache_dir=self.cache, max_workers=1)
        calls = []

        # Occupy the single worker, queue a second job, cancel just it —
        # this is what row recycling does when a row scrolls off screen.
        loader.fetch("item-a", lambda ident, data: calls.append(ident))
        self.assertTrue(session.started.wait(timeout=5))
        future = loader.fetch("item-b", lambda ident, data: calls.append(ident))
        self.assertTrue(future.cancel())

        session.release.set()
        loader._executor.shutdown(wait=True)

        self.assertEqual(calls, ["item-a"])
        self.assertEqual(session.calls, 1)

    def test_fetches_after_cancel_run_normally(self):
        session = FakeSession()
        loader = ThumbnailLoader(session, cache_dir=self.cache, max_workers=1)
        loader.cancel_pending()
        results = {}
        loader.fetch("item-c", lambda ident, data: results.update({ident: data}))
        loader._executor.shutdown(wait=True)
        self.assertEqual(results["item-c"], b"image-bytes")


if __name__ == "__main__":
    unittest.main()
