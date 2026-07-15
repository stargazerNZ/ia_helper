# PyInstaller spec for the Windows build (run from MSYS2 mingw64, see
# build.sh). MSYS2's PyInstaller ships hooks that collect the GTK DLLs,
# typelibs, and gdk-pixbuf loaders; the datas below add what those hooks
# don't cover (icon themes, compiled GSettings schemas, our app icon).
#
# Console mode is controlled by the IAHELPER_CONSOLE env var so the same
# spec serves the smoke-test build (console, --version works) and the
# release build (windowed).

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
for typelib in (MINGW / "lib/girepository-1.0").glob("*.typelib"):
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
