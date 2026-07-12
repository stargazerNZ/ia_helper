"""Download manager tests — fake HTTP session, real files in a temp dir."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ia_helper.core.config import Config
from ia_helper.core.downloads import (
    DownloadManager,
    DownloadState,
    DownloadTask,
    safe_relative_path,
)
from ia_helper.core.items import FileEntry

CONTENT = bytes(range(256)) * 5000  # ~1.25 MB, several chunks
CONTENT_MD5 = hashlib.md5(CONTENT).hexdigest()


class FakeResponse:
    def __init__(self, data: bytes, status_code: int = 200):
        self.data = data
        self.status_code = status_code

    @property
    def ok(self):
        return self.status_code < 400

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for start in range(0, len(self.data), chunk_size):
            yield self.data[start : start + chunk_size]


class FakeSession:
    """Serves CONTENT for any URL, honouring Range requests."""

    def __init__(self, content: bytes = CONTENT, honor_range: bool = True):
        self.content = content
        self.honor_range = honor_range
        self.requests: list[dict] = []

    def get(self, url, stream=False, headers=None, timeout=None):
        headers = headers or {}
        self.requests.append({"url": url, "headers": headers})
        range_header = headers.get("Range")
        if range_header and self.honor_range:
            offset = int(range_header.removeprefix("bytes=").rstrip("-"))
            if offset >= len(self.content):
                return FakeResponse(b"", status_code=416)
            return FakeResponse(self.content[offset:], status_code=206)
        return FakeResponse(self.content)


def make_manager(tmp: Path, session=None) -> DownloadManager:
    config = Config(download_dir=tmp / "downloads", max_concurrent_downloads=2)
    return DownloadManager(
        session=session or FakeSession(),
        config=config,
        state_path=tmp / "queue.json",
        autostart=False,  # tests drive _run synchronously
    )


def entry(name="video.mpg", md5=CONTENT_MD5, size=len(CONTENT)) -> FileEntry:
    return FileEntry(name=name, size=size, md5=md5, source="original")


class TestDownloadRun(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_happy_path(self):
        manager = make_manager(self.tmp)
        (task,) = manager.enqueue("item1", [entry()])
        manager._run(task)
        self.assertEqual(task.state, DownloadState.COMPLETED)
        self.assertEqual(task.dest.read_bytes(), CONTENT)
        self.assertFalse(task.part_path.exists())

    def test_checksum_mismatch_fails_and_removes_part(self):
        manager = make_manager(self.tmp)
        (task,) = manager.enqueue("item1", [entry(md5="0" * 32)])
        manager._run(task)
        self.assertEqual(task.state, DownloadState.FAILED)
        self.assertIn("checksum", task.error)
        self.assertFalse(task.dest.exists())
        self.assertFalse(task.part_path.exists())

    def test_resume_uses_range_and_verifies_whole_file(self):
        session = FakeSession()
        manager = make_manager(self.tmp, session)
        (task,) = manager.enqueue("item1", [entry()])
        half = len(CONTENT) // 2
        task.part_path.parent.mkdir(parents=True, exist_ok=True)
        task.part_path.write_bytes(CONTENT[:half])

        manager._run(task)

        self.assertEqual(task.state, DownloadState.COMPLETED)
        self.assertEqual(task.dest.read_bytes(), CONTENT)
        self.assertEqual(session.requests[-1]["headers"].get("Range"), f"bytes={half}-")

    def test_range_ignored_by_server_restarts_cleanly(self):
        session = FakeSession(honor_range=False)
        manager = make_manager(self.tmp, session)
        (task,) = manager.enqueue("item1", [entry()])
        task.part_path.parent.mkdir(parents=True, exist_ok=True)
        task.part_path.write_bytes(b"garbage that would corrupt the hash")

        manager._run(task)

        self.assertEqual(task.state, DownloadState.COMPLETED)
        self.assertEqual(task.dest.read_bytes(), CONTENT)

    def test_already_complete_part_finalizes_via_416(self):
        manager = make_manager(self.tmp)
        (task,) = manager.enqueue("item1", [entry()])
        task.part_path.parent.mkdir(parents=True, exist_ok=True)
        task.part_path.write_bytes(CONTENT)

        manager._run(task)

        self.assertEqual(task.state, DownloadState.COMPLETED)
        self.assertEqual(task.dest.read_bytes(), CONTENT)

    def test_existing_complete_file_short_circuits_at_enqueue(self):
        manager = make_manager(self.tmp)
        dest = self.tmp / "downloads" / "item1" / "video.mpg"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(CONTENT)
        (task,) = manager.enqueue("item1", [entry()])
        self.assertEqual(task.state, DownloadState.COMPLETED)


class TestQueueBehaviour(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_unsafe_names_are_skipped_not_fatal(self):
        manager = make_manager(self.tmp)
        created = manager.enqueue(
            "item1", [entry(name="../../etc/passwd"), entry(name="good.mpg")]
        )
        self.assertEqual([t.file_name for t in created], ["good.mpg"])

    def test_duplicate_active_dest_not_requeued(self):
        manager = make_manager(self.tmp)
        first = manager.enqueue("item1", [entry()])
        second = manager.enqueue("item1", [entry()])
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_subdirectory_file_names_stay_inside_item_dir(self):
        manager = make_manager(self.tmp)
        (task,) = manager.enqueue("item1", [entry(name="disc1/track01.flac")])
        expected = self.tmp / "downloads" / "item1" / "disc1" / "track01.flac"
        self.assertEqual(task.dest, expected)

    def test_persistence_round_trip_requeues_running(self):
        manager = make_manager(self.tmp)
        task_a, task_b = manager.enqueue(
            "item1", [entry(name="a.mpg"), entry(name="b.mpg")]
        )
        task_a.state = DownloadState.RUNNING
        task_b.state = DownloadState.PAUSED
        manager._save()

        reloaded = make_manager(self.tmp)
        states = {t.file_name: t.state for t in reloaded.tasks()}
        self.assertEqual(states["a.mpg"], DownloadState.QUEUED)
        self.assertEqual(states["b.mpg"], DownloadState.PAUSED)

    def test_state_file_is_valid_json(self):
        manager = make_manager(self.tmp)
        manager.enqueue("item1", [entry()])
        payload = json.loads((self.tmp / "queue.json").read_text())
        self.assertEqual(payload[0]["identifier"], "item1")

    def test_pause_and_resume_queued_task(self):
        manager = make_manager(self.tmp)
        (task,) = manager.enqueue("item1", [entry()])
        manager.pause(task)
        self.assertEqual(task.state, DownloadState.PAUSED)
        manager.resume(task)
        self.assertEqual(task.state, DownloadState.QUEUED)

    def test_cancel_removes_part(self):
        manager = make_manager(self.tmp)
        (task,) = manager.enqueue("item1", [entry()])
        task.part_path.parent.mkdir(parents=True, exist_ok=True)
        task.part_path.write_bytes(b"partial")
        manager.cancel(task)
        self.assertEqual(task.state, DownloadState.CANCELLED)
        self.assertFalse(task.part_path.exists())

    def test_clear_finished(self):
        manager = make_manager(self.tmp)
        task_a, task_b = manager.enqueue(
            "item1", [entry(name="a.mpg"), entry(name="b.mpg")]
        )
        task_a.state = DownloadState.COMPLETED
        manager.clear_finished()
        self.assertEqual([t.file_name for t in manager.tasks()], ["b.mpg"])


class TestSafeRelativePath(unittest.TestCase):
    def test_rejects_traversal_and_absolute(self):
        for bad in ("../x", "a/../../x", "/etc/passwd", "", "c:evil"):
            with self.assertRaises(ValueError, msg=bad):
                safe_relative_path(bad)

    def test_accepts_normal_and_nested(self):
        self.assertEqual(str(safe_relative_path("a.mpg")), "a.mpg")
        self.assertEqual(str(safe_relative_path("disc1/a.flac")), "disc1/a.flac")


class TestTaskUrl(unittest.TestCase):
    def test_url_quotes_spaces_keeps_slashes(self):
        task = DownloadTask(
            identifier="my item", file_name="disc 1/track 01.flac", dest=Path("x")
        )
        self.assertEqual(
            task.url,
            "https://archive.org/download/my%20item/disc%201/track%2001.flac",
        )


if __name__ == "__main__":
    unittest.main()
