"""Bulk manager tests — fake scrape/item clients, real DownloadManager."""

import tempfile
import unittest
from pathlib import Path

from ia_helper.core.bulk import BulkJob, BulkJobState, BulkManager
from ia_helper.core.config import Config
from ia_helper.core.downloads import DownloadManager, DownloadState
from ia_helper.core.items import FileEntry, ItemDetails
from ia_helper.core.scrape import ScrapeItem


class FakeScrapeClient:
    def __init__(self, pages):
        self._pages = pages

    def pages(self, query, fields=None):
        yield from self._pages


class FakeItemClient:
    def __init__(self, catalog, fail=()):
        self.catalog = catalog
        self.fail = set(fail)
        self.fetched = []

    def get_item(self, identifier):
        self.fetched.append(identifier)
        if identifier in self.fail:
            raise RuntimeError(f"boom: {identifier}")
        return self.catalog[identifier]


class NoopSession:
    def get(self, *args, **kwargs):
        raise AssertionError("downloads must not run in these tests")


def details(identifier, files):
    return ItemDetails(identifier=identifier, title=f"Title {identifier}", files=files)


def entry(name, size=10, source="original", private=False, fmt=""):
    return FileEntry(name=name, size=size, md5="x", source=source,
                     private=private, format=fmt)


class TestBulkFeeder(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.downloads = DownloadManager(
            session=NoopSession(),
            config=Config(download_dir=self.tmp / "dl", max_concurrent_downloads=1),
            state_path=self.tmp / "queue.json",
            autostart=False,
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def make_manager(self, scrape_pages, catalog, fail=(), low_water=10_000):
        # autostart=False: tests drive _process_job synchronously. High
        # low_water so the throttle never blocks (downloads never run here).
        return BulkManager(
            scrape_client=FakeScrapeClient(scrape_pages),
            item_client=FakeItemClient(catalog, fail=fail),
            download_manager=self.downloads,
            state_path=self.tmp / "bulk.json",
            autostart=False,
            low_water=low_water,
        )

    def run_job(self, manager, **kwargs) -> BulkJob:
        job = manager.start(kwargs.pop("query", "collection:x"),
                            kwargs.pop("label", "x"),
                            kwargs.pop("original_only", False),
                            kwargs.pop("total_items", 0))
        manager._process_job(job)
        return job

    def test_feeds_all_items_and_completes(self):
        pages = [[ScrapeItem("item1"), ScrapeItem("item2")]]
        catalog = {
            "item1": details("item1", [entry("a.mpg")]),
            "item2": details("item2", [entry("b.mpg"), entry("c.txt")]),
        }
        manager = self.make_manager(pages, catalog)
        job = self.run_job(manager, total_items=2)

        self.assertEqual(job.state, BulkJobState.COMPLETED)
        self.assertEqual(job.processed_items, 2)
        self.assertEqual(job.enqueued_files, 3)
        queued = self.downloads.tasks()
        self.assertEqual(len(queued), 3)
        self.assertEqual(queued[0].item_title, "Title item1")

    def test_restricted_items_skipped_without_metadata_fetch(self):
        pages = [[ScrapeItem("open1"), ScrapeItem("locked", access_restricted=True)]]
        catalog = {"open1": details("open1", [entry("a.mpg")])}
        manager = self.make_manager(pages, catalog)
        job = self.run_job(manager, total_items=2)

        self.assertEqual(job.state, BulkJobState.COMPLETED)
        self.assertEqual(job.skipped_restricted, 1)
        self.assertNotIn("locked", manager._items.fetched)

    def test_file_policy_original_private_drm(self):
        files = [
            entry("orig.mpg", source="original"),
            entry("deriv.mp4", source="derivative"),
            entry("secret.pdf", private=True),
            entry("book.lcpdf", fmt="LCP Encrypted PDF"),
        ]
        catalog = {"item1": details("item1", files)}
        manager = self.make_manager([[ScrapeItem("item1")]], catalog)
        job = self.run_job(manager, original_only=True, total_items=1)

        names = [t.file_name for t in self.downloads.tasks()]
        self.assertEqual(names, ["orig.mpg"])
        self.assertEqual(job.enqueued_files, 1)

    def test_existing_complete_files_skipped_silently(self):
        dest = self.tmp / "dl" / "item1" / "a.mpg"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"0123456789")  # size 10 matches entry()
        catalog = {"item1": details("item1", [entry("a.mpg"), entry("b.mpg")])}
        manager = self.make_manager([[ScrapeItem("item1")]], catalog)
        job = self.run_job(manager, total_items=1)

        names = [t.file_name for t in self.downloads.tasks()]
        self.assertEqual(names, ["b.mpg"])
        self.assertEqual(job.enqueued_files, 1)

    def test_resume_skips_processed_without_metadata_fetches(self):
        pages = [[ScrapeItem("item1"), ScrapeItem("item2"), ScrapeItem("item3")]]
        catalog = {
            "item2": details("item2", [entry("b.mpg")]),
            "item3": details("item3", [entry("c.mpg")]),
        }
        manager = self.make_manager(pages, catalog)
        job = manager.start("collection:x", "x", False, total_items=3)
        job.processed_items = 1  # item1 done in a previous session
        manager._process_job(job)

        self.assertEqual(job.state, BulkJobState.COMPLETED)
        # item1's metadata was never fetched again.
        self.assertEqual(manager._items.fetched, ["item2", "item3"])

    def test_pause_interrupts_mid_walk(self):
        pages = [[ScrapeItem("item1"), ScrapeItem("item2")]]

        class PausingItemClient(FakeItemClient):
            def __init__(self, catalog, manager_ref):
                super().__init__(catalog)
                self.manager_ref = manager_ref

            def get_item(self, identifier):
                result = super().get_item(identifier)
                # Simulate the user pausing right after the first item.
                self.manager_ref[0].pause(self.manager_ref[0].jobs()[0])
                return result

        catalog = {"item1": details("item1", [entry("a.mpg")]),
                   "item2": details("item2", [entry("b.mpg")])}
        manager_ref = []
        manager = BulkManager(
            scrape_client=FakeScrapeClient(pages),
            item_client=PausingItemClient(catalog, manager_ref),
            download_manager=self.downloads,
            state_path=self.tmp / "bulk.json",
            autostart=False,
            low_water=10_000,
        )
        manager_ref.append(manager)
        job = manager.start("collection:x", "x", False, total_items=2)
        manager._process_job(job)

        self.assertEqual(job.state, BulkJobState.PAUSED)
        self.assertEqual(job.processed_items, 1)

    def test_repeated_failures_fail_the_job(self):
        pages = [[ScrapeItem(f"item{n}") for n in range(1, 8)]]
        manager = self.make_manager(pages, catalog={},
                                    fail={f"item{n}" for n in range(1, 8)})
        job = self.run_job(manager, total_items=7)

        self.assertEqual(job.state, BulkJobState.FAILED)
        self.assertIn("repeated failures", job.error)
        self.assertLessEqual(len(manager._items.fetched), 6)

    def test_persistence_running_restores_paused(self):
        manager = self.make_manager([[]], catalog={})
        job = manager.start("collection:x", "label x", True, total_items=5)
        job.processed_items = 3
        manager._save()

        reloaded = self.make_manager([[]], catalog={})
        (restored,) = reloaded.jobs()
        self.assertEqual(restored.state, BulkJobState.PAUSED)
        self.assertEqual(restored.processed_items, 3)
        self.assertTrue(restored.original_only)
        self.assertEqual(restored.label, "label x")


class TestPruneFinished(unittest.TestCase):
    def test_prune_keeps_newest_finished(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloads = DownloadManager(
                session=NoopSession(),
                config=Config(download_dir=Path(tmp) / "dl",
                              max_concurrent_downloads=1),
                state_path=Path(tmp) / "queue.json",
                autostart=False,
            )
            created = downloads.enqueue(
                "item1", [entry(f"f{n}.bin") for n in range(6)]
            )
            for task in created[:4]:
                task.state = DownloadState.COMPLETED
            downloads.prune_finished(max_kept=2)

            remaining = downloads.tasks()
            finished = [t for t in remaining if t.state == DownloadState.COMPLETED]
            self.assertEqual(len(finished), 2)
            self.assertEqual({t.file_name for t in finished},
                             {"f2.bin", "f3.bin"})
            self.assertEqual(len(remaining), 4)  # 2 finished + 2 queued


if __name__ == "__main__":
    unittest.main()
