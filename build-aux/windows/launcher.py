"""Frozen-app entry point (PyInstaller).

Points GTK's data lookups into the bundle before anything GTK is
imported — a frozen app has no MSYS2 prefix to fall back on — and
regenerates the gdk-pixbuf loader cache for wherever the app is actually
installed (the cache format stores absolute paths, so a build-time cache
would only work on the build machine).
"""

import os
import subprocess
import sys


def _setup_frozen_environment() -> None:
    bundle = sys._MEIPASS
    share = os.path.join(bundle, "share")
    os.environ.setdefault(
        "GSETTINGS_SCHEMA_DIR", os.path.join(share, "glib-2.0", "schemas")
    )
    os.environ["XDG_DATA_DIRS"] = share

    loaders_dir = os.path.join(bundle, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders")
    query_tool = os.path.join(bundle, "gdk-pixbuf-query-loaders.exe")
    if not (os.path.isdir(loaders_dir) and os.path.exists(query_tool)):
        return
    cache_home = os.path.join(
        os.environ.get("LOCALAPPDATA", bundle), "ia-helper", "cache"
    )
    os.makedirs(cache_home, exist_ok=True)
    cache_file = os.path.join(cache_home, "pixbuf-loaders.cache")
    env = dict(os.environ, GDK_PIXBUF_MODULEDIR=loaders_dir)
    try:
        result = subprocess.run(
            [query_tool],
            env=env,
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and result.stdout:
            with open(cache_file, "wb") as handle:
                handle.write(result.stdout)
            os.environ["GDK_PIXBUF_MODULE_FILE"] = cache_file
    except (OSError, subprocess.SubprocessError):
        pass  # PNG/JPEG still work via GTK's built-in loaders


if getattr(sys, "frozen", False):
    _setup_frozen_environment()

from ia_helper.main import main  # noqa: E402

sys.exit(main())
