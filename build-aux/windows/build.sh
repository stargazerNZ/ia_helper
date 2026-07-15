#!/usr/bin/env bash
# Build the Windows package: PyInstaller onedir app, NSIS installer, and
# portable zip. Run from an MSYS2 mingw64 shell (or any bash that can see
# the MSYS2 binaries), with a mingw-python venv holding internetarchive:
#
#   python -m venv --system-site-packages ~/.venvs/ia_helper-win
#   ~/.venvs/ia_helper-win/bin/python -m pip install internetarchive
#   bash build-aux/windows/build.sh
#
# Needs (pacman): mingw-w64-x86_64-{gtk4,libadwaita,python,python-gobject,
# python-pip,pyinstaller,nsis,librsvg,adwaita-icon-theme}.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

# PyInstaller resolves DLL dependencies via PATH. Git for Windows ships its
# own (older) GLib stack in ITS mingw64/bin; if that wins the search, the
# bundle mixes libraries and _gi dies with "procedure could not be found".
# Force the real MSYS2 prefix to the front.
export PATH="/c/msys64/mingw64/bin:$PATH"
export MINGW_PREFIX="${MINGW_PREFIX:-C:/msys64/mingw64}"
PYTHON="${IAHELPER_PYTHON:-$HOME/.venvs/ia_helper-win/bin/python.exe}"
MAKENSIS="${MAKENSIS:-/mingw64/bin/makensis.exe}"
VERSION="$("$PYTHON" -c "import sys; sys.path.insert(0, r'$REPO'); import ia_helper; print(ia_helper.__version__)")"

echo "== building IA Helper $VERSION for Windows =="

build() {
    IAHELPER_CONSOLE="$1" "$PYTHON" -m PyInstaller --noconfirm \
        --workpath "$HERE/build" --distpath "$HERE/dist" \
        "$HERE/ia-helper.spec"
}

# Console build first: --version proves the frozen import chain.
build 1
"$HERE/dist/ia-helper/ia-helper.exe" --version

# Release build (windowed).
build 0

"$MAKENSIS" -DVERSION="$VERSION" "$HERE/installer.nsi"

echo "== artifacts =="
ls -lh "$HERE"/ia-helper-*-setup.exe
echo "portable tree: $HERE/dist/ia-helper (zip it for the portable download)"
