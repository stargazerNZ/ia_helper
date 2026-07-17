# PyInstaller spec for the Windows build (run from MSYS2 mingw64, see
# build.sh). MSYS2's PyInstaller ships hooks that collect the GTK DLLs,
# typelibs, and gdk-pixbuf loaders; the datas below add what those hooks
# don't cover (icon themes, compiled GSettings schemas, our app icon).
#
# Console mode is controlled by the IAHELPER_CONSOLE env var so the same
# spec serves the smoke-test build (console, --version works) and the
# release build (windowed).
#
# Startup-time note (2026-07-17): on Windows, launch time with Defender's
# real-time protection on was measured at ~5-6s vs ~1-2s with it off —
# the ~120-DLL, ~75-typelib bundle gives it a lot to scan. The typelib
# count is trimmed below (see REQUIRED_TYPELIBS) since typelibs are
# on-demand metadata, not eager dependencies. The DLL side was
# investigated and is NOT similarly trimmable: `objdump -p` on
# libgtk-4-1.dll shows GStreamer (libgstreamer/-allocators/-d3d12/-gl/
# -play/-video) under its regular (non-delay-load) Import Tables — this
# MSYS2 GTK4 build links GStreamer directly for GtkVideo/GtkMediaFile
# support, so those DLLs are mandatory for libgtk-4-1.dll to load at all,
# regardless of whether the app ever uses a video widget. Don't re-attempt
# removing them without re-verifying against a GTK4 build that makes this
# an optional/plugin dependency instead.

import os
from pathlib import Path

MINGW = Path(os.environ.get("MINGW_PREFIX", "C:/msys64/mingw64"))
REPO = Path(SPECPATH).resolve().parents[1]
CONSOLE = os.environ.get("IAHELPER_CONSOLE", "0") == "1"

datas = [
    (
        str(REPO / "data/icons/hicolor/scalable/apps/io.github.stargazernz.IAHelper.svg"),
        "share/icons/hicolor/scalable/apps",
    ),
]
for extra in (
    "share/glib-2.0/schemas/gschemas.compiled",
    "share/icons/Adwaita",
    "share/icons/hicolor",
):
    source = MINGW / extra
    if source.exists():
        target = extra if source.is_dir() else str(Path(extra).parent)
        datas.append((str(source), target))

# PyInstaller's gi hooks only collect the GLib base stack; the GTK4 layer
# must be gathered explicitly (verified: without this, Gtk-4.0.typelib and
# libgtk-4-1.dll are absent and the frozen app dies at require_version).
#
# MSYS2's girepository-1.0 directory holds ~75 typelibs from every
# gi-enabled package pacman has ever installed on the build machine
# (GStreamer's entire family, CUDA, WebRTC, X11 bindings — none of which
# ia_helper touches); bundling all of them was adding ~60 unnecessary
# files for Windows Defender to scan on every launch. This list is the
# true, authoritative transitive closure of what Gtk-4.0 + Adw-1 declare
# as GI-level dependencies (each namespace's typelib "Requires" its own
# deps), derived by actually asking GObject-Introspection rather than
# guessing:
#
#   gi.require_version("GIRepository", "3.0"); gi.require_version("Gtk", "4.0")
#   gi.require_version("Adw", "1")
#   repo = GIRepository.Repository.dup_default()
#   # walk repo.get_immediate_dependencies(ns) from "Gtk" and "Adw"
#
# Regenerate this list the same way if a future gi.require_version() is
# added for something not already covered here; typelibs are lightweight
# introspection metadata loaded lazily by namespace, not eager PE
# dependencies, so trimming them (unlike DLLs) carries no load-time risk
# beyond "the namespace you forgot to add isn't found."
REQUIRED_TYPELIBS = {
    "Adw-1", "GLib-2.0", "GModule-2.0", "GObject-2.0", "Gdk-4.0",
    "GdkPixbuf-2.0", "Gio-2.0", "Graphene-1.0", "Gsk-4.0", "Gtk-4.0",
    "HarfBuzz-0.0", "Pango-1.0", "PangoCairo-1.0", "cairo-1.0",
    "freetype2-2.0",
}
for typelib in (MINGW / "lib/girepository-1.0").glob("*.typelib"):
    if typelib.stem in REQUIRED_TYPELIBS:
        datas.append((str(typelib), "gi_typelibs"))

binaries = []
for dll in (
    "libgtk-4-1.dll",
    "libadwaita-1-0.dll",
    "libgdk_pixbuf-2.0-0.dll",
    "librsvg-2-2.dll",
    "gdk-pixbuf-query-loaders.exe",  # regenerates the loader cache at runtime
):
    source = MINGW / "bin" / dll
    if source.exists():
        binaries.append((str(source), "."))
# Pixbuf loaders as *binaries* so their own deps get dependency-scanned.
for loader in (MINGW / "lib/gdk-pixbuf-2.0/2.10.0/loaders").glob("*.dll"):
    binaries.append((str(loader), "lib/gdk-pixbuf-2.0/2.10.0/loaders"))

a = Analysis(
    [str(REPO / "build-aux/windows/launcher.py")],
    pathex=[str(REPO)],
    datas=datas,
    binaries=binaries,
    hiddenimports=[
        "gi",
        "gi.repository.Gtk",
        "gi.repository.Adw",
        "gi.repository.Gdk",
        "gi.repository.Gio",
        "gi.repository.GLib",
        "gi.repository.GObject",
        "gi.repository.Pango",
        "internetarchive",
    ],
    noarchive=False,
)

# The dependency scan of the force-added GTK DLLs drags in Windows system
# libraries; bundling those (ucrtbase especially) shadows the real system
# copies and breaks _gi with "specified procedure could not be found".
SYSTEM_DLLS = {"ucrtbase.dll", "vulkan-1.dll"}
a.binaries = [
    entry for entry in a.binaries
    if Path(entry[0]).name.lower() not in SYSTEM_DLLS
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="ia-helper",
    icon=str(REPO / "build-aux/windows/ia-helper.ico"),
    console=CONSOLE,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="ia-helper",
)
