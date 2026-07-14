"""User configuration: plain JSON under XDG paths.

Deliberately not GSettings — no schema compilation step, works identically
in a venv, a .deb, a Flatpak, and a future Windows build.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR_NAME = "ia-helper"

MAX_CONCURRENT_LIMIT = 5  # politeness cap; see core.api connection budget


def _xdg_dir(env_var: str, fallback: str) -> Path:
    value = os.environ.get(env_var)
    return Path(value) if value else Path.home() / fallback


def _windows_dir(env_var: str, fallback: str) -> Path:
    value = os.environ.get(env_var)
    return Path(value) if value else Path.home() / "AppData" / fallback


def config_dir(platform: str | None = None) -> Path:
    """Per-user config directory (XDG on Unix, %APPDATA% on Windows)."""
    if (platform or sys.platform) == "win32":
        return _windows_dir("APPDATA", "Roaming") / APP_DIR_NAME
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / APP_DIR_NAME


def state_dir(platform: str | None = None) -> Path:
    """Per-user state directory (queue, bulk jobs)."""
    if (platform or sys.platform) == "win32":
        return _windows_dir("LOCALAPPDATA", "Local") / APP_DIR_NAME / "state"
    return _xdg_dir("XDG_STATE_HOME", ".local/state") / APP_DIR_NAME


def cache_dir(platform: str | None = None) -> Path:
    """Per-user cache directory (thumbnails)."""
    if (platform or sys.platform) == "win32":
        return _windows_dir("LOCALAPPDATA", "Local") / APP_DIR_NAME / "cache"
    return _xdg_dir("XDG_CACHE_HOME", ".cache") / APP_DIR_NAME


def default_download_dir() -> Path:
    """The user's XDG download directory (per user-dirs.dirs), else ~/Downloads."""
    dirs_file = _xdg_dir("XDG_CONFIG_HOME", ".config") / "user-dirs.dirs"
    try:
        for line in dirs_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("XDG_DOWNLOAD_DIR"):
                value = line.split("=", 1)[1].strip().strip('"')
                value = value.replace("$HOME", str(Path.home()))
                if value:
                    return Path(value)
    except OSError:
        pass
    return Path.home() / "Downloads"


@dataclass
class Config:
    download_dir: Path = field(default_factory=default_download_dir)
    max_concurrent_downloads: int = 3

    def normalized(self) -> "Config":
        self.download_dir = Path(self.download_dir).expanduser()
        self.max_concurrent_downloads = max(
            1, min(MAX_CONCURRENT_LIMIT, int(self.max_concurrent_downloads))
        )
        return self


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return Config().normalized()
    config = Config()
    if "download_dir" in raw:
        config.download_dir = Path(raw["download_dir"])
    if "max_concurrent_downloads" in raw:
        try:
            config.max_concurrent_downloads = int(raw["max_concurrent_downloads"])
        except (TypeError, ValueError):
            pass
    return config.normalized()


def save_config(config: Config, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "download_dir": str(config.download_dir),
        "max_concurrent_downloads": config.max_concurrent_downloads,
    }
    path.write_text(json.dumps(payload, indent=2))
