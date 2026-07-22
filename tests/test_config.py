"""Config tests — temp paths only."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ia_helper.core.config import (
    Config,
    cache_dir,
    config_dir,
    load_config,
    save_config,
    state_dir,
)


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

    def test_bandwidth_limit_round_trip(self):
        config = Config(bandwidth_limit_kbps=512)
        save_config(config, self.path)
        loaded = load_config(self.path)
        self.assertEqual(loaded.bandwidth_limit_kbps, 512)

    def test_bandwidth_limit_defaults_unlimited_and_clamps_negative(self):
        self.assertEqual(load_config(self.path).bandwidth_limit_kbps, 0)
        config = Config(bandwidth_limit_kbps=-5).normalized()
        self.assertEqual(config.bandwidth_limit_kbps, 0)


class TestPlatformDirs(unittest.TestCase):
    def test_unix_uses_xdg(self):
        env = {
            "XDG_CONFIG_HOME": "/xdg/config",
            "XDG_STATE_HOME": "/xdg/state",
            "XDG_CACHE_HOME": "/xdg/cache",
        }
        with mock.patch.dict(os.environ, env):
            self.assertEqual(config_dir("linux"), Path("/xdg/config/ia-helper"))
            self.assertEqual(state_dir("linux"), Path("/xdg/state/ia-helper"))
            self.assertEqual(cache_dir("linux"), Path("/xdg/cache/ia-helper"))

    def test_windows_uses_appdata(self):
        env = {
            "APPDATA": r"C:\Users\x\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\x\AppData\Local",
        }
        with mock.patch.dict(os.environ, env):
            self.assertEqual(
                config_dir("win32"),
                Path(r"C:\Users\x\AppData\Roaming") / "ia-helper",
            )
            self.assertEqual(
                state_dir("win32"),
                Path(r"C:\Users\x\AppData\Local") / "ia-helper" / "state",
            )
            self.assertEqual(
                cache_dir("win32"),
                Path(r"C:\Users\x\AppData\Local") / "ia-helper" / "cache",
            )


if __name__ == "__main__":
    unittest.main()
