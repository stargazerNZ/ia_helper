"""Config tests — temp paths only."""

import tempfile
import unittest
from pathlib import Path

from ia_helper.core.config import Config, load_config, save_config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "config.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_round_trip(self):
        config = Config(download_dir=Path("/data/ia"), max_concurrent_downloads=2)
        save_config(config, self.path)
        loaded = load_config(self.path)
        self.assertEqual(loaded.download_dir, Path("/data/ia"))
        self.assertEqual(loaded.max_concurrent_downloads, 2)

    def test_missing_file_yields_defaults(self):
        config = load_config(self.path)
        self.assertGreaterEqual(config.max_concurrent_downloads, 1)
        self.assertTrue(str(config.download_dir))

    def test_corrupt_file_yields_defaults(self):
        self.path.write_text("{not json")
        config = load_config(self.path)
        self.assertEqual(config.max_concurrent_downloads, 3)

    def test_concurrency_clamped(self):
        config = Config(max_concurrent_downloads=99).normalized()
        self.assertEqual(config.max_concurrent_downloads, 5)
        config = Config(max_concurrent_downloads=0).normalized()
        self.assertEqual(config.max_concurrent_downloads, 1)


if __name__ == "__main__":
    unittest.main()
