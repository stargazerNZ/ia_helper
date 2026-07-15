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
# python-pip,pyinstaller,librsvg,adwaita-icon-theme}, plus Inno Setup 6
# (winget install JRSoftware.InnoSetup) for the installer.
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
ISCC="${ISCC:-}"
if [ -z "$ISCC" ]; then
    for candidate in \
        "$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" \
        "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"; do
        [ -f "$candidate" ] && ISCC="$candidate" && break
    done
fi
[ -n "$ISCC" ] || { echo "Inno Setup 6 (ISCC.exe) not found" >&2; exit 1; }

# Optional Authenticode signing. Set IAHELPER_SIGN_ARGS to the
# `signtool sign` arguments minus the file, e.g. for a Certum SimplySign
# certificate:
#   IAHELPER_SIGN_ARGS='/sha1 <thumbprint> /fd sha256 /tr http://time.certum.pl /td sha256'
# Unset (the default until a certificate exists), the build is identical
# to an unsigned build. See RELEASING.md "Code signing (Windows)".
SIGNTOOL="${SIGNTOOL:-}"
if [ -z "$SIGNTOOL" ]; then
    SIGNTOOL=$(ls -1 "C:/Program Files (x86)/Windows Kits/10/bin/"*/x64/signtool.exe 2>/dev/null | sort -V | tail -1 || true)
fi

sign_file() {
    [ -n "${IAHELPER_SIGN_ARGS:-}" ] || return 0
    [ -n "$SIGNTOOL" ] || {
        echo "IAHELPER_SIGN_ARGS is set but signtool.exe was not found" >&2
        exit 1
    }
    echo "signing: $1"
    # MSYS bash converts signtool's slash switches (/fd, /tr, /pa, …) into
    # C:/Program Files/Git/… paths; exclude ALL conversion and hand the
    # file over as a native Windows path instead. Word-splitting of
    # IAHELPER_SIGN_ARGS is intentional.
    MSYS2_ARG_CONV_EXCL="*" "$SIGNTOOL" sign $IAHELPER_SIGN_ARGS "$(cygpath -w "$1")"
}
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

if [ -n "${IAHELPER_SIGN_ARGS:-}" ]; then
    sign_file "$HERE/dist/ia-helper/ia-helper.exe"
    sign_file "$HERE/dist/ia-helper/_internal/gdk-pixbuf-query-loaders.exe"
else
    echo "signing: disabled (IAHELPER_SIGN_ARGS not set)"
fi

# MSYS2_ARG_CONV_EXCL stops bash mangling the /D and /S switches into
# paths; the .iss path argument is still converted normally.
ISCC_ARGS=("/DVERSION=$VERSION" "/DDISTDIR=dist")
if [ -n "${IAHELPER_SIGN_ARGS:-}" ]; then
    # $f is Inno's file placeholder and must reach ISCC literally; with
    # SignTool configured, Inno also signs the uninstaller.
    ISCC_ARGS+=("/DSIGN" "/Ssigntool=\"$SIGNTOOL\" sign $IAHELPER_SIGN_ARGS \$f")
fi
MSYS2_ARG_CONV_EXCL="/D;/S" "$ISCC" "${ISCC_ARGS[@]}" "$HERE/installer.iss"

if [ -n "${IAHELPER_SIGN_ARGS:-}" ]; then
    MSYS2_ARG_CONV_EXCL="*" "$SIGNTOOL" verify /pa \
        "$(cygpath -w "$HERE/ia-helper-$VERSION-windows-x64-setup.exe")"
fi

echo "== artifacts =="
ls -lh "$HERE"/ia-helper-*-setup.exe
echo "portable tree: $HERE/dist/ia-helper (zip it for the portable download)"
