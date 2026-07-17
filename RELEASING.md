# Releasing IA Helper

Two separate things live in this document: the **GitHub release
procedure** (used for every release so far, v1.0.0 through the current
version — see `ia_helper/__init__.py` for what that is) and the
**going-public / Flathub checklist** (still pending — the repo is
private and the app isn't on Flathub yet).

## GitHub release procedure (repeat for every version)

This is the actual recipe used each time, combining a local WSL Ubuntu
environment (for the Linux artifacts) and MSYS2 on the same Windows box
(for Windows). No CI is involved; everything is built and verified by
hand before publishing.

1. **Bump the version** in `ia_helper/__init__.py`, `pyproject.toml`, add
   a `<release>` entry to the metainfo, and add a `debian/changelog`
   entry. Commit and push to `main`.
2. **Tag and push**: `git tag -a vX.Y.Z -m "IA Helper X.Y.Z"` then
   `git push origin vX.Y.Z`.
3. **Linux artifacts, in a WSL Ubuntu clone** (kept at `~/ia_helper-release`
   in WSL, separate from the Windows working copy — see
   ARCHITECTURE.md/ROADMAP.md for why a WSL clone specifically):
   ```sh
   cd ~/ia_helper-release && git fetch -q origin && git checkout vX.Y.Z
   dpkg-buildpackage -us -uc -b
   flatpak-builder --user --force-clean --repo=flatpak-repo flatpak-build \
       build-aux/flatpak/io.github.stargazernz.IAHelper.json
   flatpak build-bundle flatpak-repo io.github.stargazernz.IAHelper-X.Y.Z.flatpak \
       io.github.stargazernz.IAHelper --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo
   ```
   Verify: `flatpak install` the bundle and run `--version`; `dpkg -I` the
   `.deb` and check its `Version` field.
4. **Windows artifacts**, from an MSYS2-capable shell on Windows:
   ```sh
   bash build-aux/windows/build.sh   # console smoke test, windowed build, installer
   ```
   Then zip the portable tree:
   `Compress-Archive -Path build-aux\windows\dist\ia-helper\* -DestinationPath ia-helper-X.Y.Z-windows-x64-portable.zip`.
   Verify with a **full silent install/launch/uninstall cycle** — this
   caught a real bug once (Inno Setup leaving a previous version's files
   behind on upgrade; see ROADMAP.md):
   ```powershell
   .\ia-helper-X.Y.Z-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES
   # confirm exe/shortcut/registry version, launch it, then:
   & "$env:LOCALAPPDATA\Programs\IA Helper\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
   # confirm registry entry and install dir are both gone
   ```
5. **Checksums**: `sha256sum` all four binaries (`.deb`, `.flatpak`,
   `-setup.exe`, `-portable.zip`) into one `SHA256SUMS` file.
6. **Publish**:
   ```sh
   gh release create vX.Y.Z --title "IA Helper X.Y.Z" --notes-file notes.md \
       ia-helper_X.Y.Z_all.deb io.github.stargazernz.IAHelper-X.Y.Z.flatpak \
       ia-helper-X.Y.Z-windows-x64-setup.exe ia-helper-X.Y.Z-windows-x64-portable.zip \
       SHA256SUMS --repo stargazerNZ/ia_helper
   ```
   `gh release view --json ... /releases/tags/vX.Y.Z` is occasionally
   flaky (GitHub's "Unicorn" transient-error page) even when the release
   itself is fine — if so, verify via `gh api repos/.../releases` (list,
   not tag-lookup) and `gh api repos/.../releases/<id>/assets` instead.

Run the full test suite (`python -m unittest discover tests`, both the
plain Windows Python and the MSYS2 mingw venv — `internetarchive` is only
importable in the latter, which is why `core/api.py` has no dedicated
unit test file) before tagging.

## Going public / Flathub checklist (still pending)

A one-time sequence, independent of which version is current — no need
to redo a GitHub release for this, it builds from whatever tag already
exists once the repo goes public.

### 1. Screenshots (on the Linux VM)

Take three window screenshots (Alt+PrintScreen in GNOME captures the
focused window, saved to ~/Pictures/Screenshots), showing:

| File | Content |
|---|---|
| `data/screenshots/search.png` | Search results for something visual (e.g. `collection:prelinger`) |
| `data/screenshots/item.png` | An item page with a few files selected |
| `data/screenshots/downloads.png` | The downloads view with a couple of item groups in flight |

Guidelines: default window size or larger, light or dark consistently,
no personal info visible (sign out or avoid the menu). Commit them at
exactly those paths — the metainfo `<screenshots>` URLs point there.

### 2. Validate (on the VM)

```sh
desktop-file-validate data/io.github.stargazernz.IAHelper.desktop
appstreamcli validate data/io.github.stargazernz.IAHelper.metainfo.xml
```

`appstreamcli` warns about unreachable screenshot URLs until the repo is
public — that specific warning is expected at this stage; anything else
should be fixed.

### 3. Make the repository public

GitHub → Settings → General → Danger Zone → Change visibility. Required
for Flathub verification (app ID `io.github.stargazernz.IAHelper` must
match the public repo) and for the screenshot URLs to resolve.

### 4. Verify the Flathub manifest builds

The submission manifest is `build-aux/flathub/io.github.stargazernz.IAHelper.json`
(identical to the local one except it builds from the git tag, not the
working directory). Test it on the VM:

```sh
cp build-aux/flatpak/python3-internetarchive.json build-aux/flathub/
flatpak-builder --user --install --force-clean flathub-build \
    build-aux/flathub/io.github.stargazernz.IAHelper.json
flatpak run io.github.stargazernz.IAHelper
```

### 5. Submit to Flathub

Follow https://docs.flathub.org/docs/for-app-authors/submission:
fork `flathub/flathub`, create a branch named `io.github.stargazernz.IAHelper`
from the `new-pr` base branch, add two files at the repo root —
`io.github.stargazernz.IAHelper.json` (the flathub manifest) and
`python3-internetarchive.json` — and open a PR against `new-pr`.
Respond to reviewer feedback; once merged, Flathub creates the app repo
and the build goes live.

### 6. After acceptance

- Announce/link the Flathub page in the README.
- Subsequent releases: the regular GitHub release procedure (above)
  covers the version bump; additionally update the tag in the Flathub
  app repo (a PR against `flathub/io.github.stargazernz.IAHelper`).

## Code signing (Windows)

**Current status: artifacts ship unsigned.** SmartScreen's "Windows
protected your PC" prompt ("More info → Run anyway") is expected on the
setup exe. The build hooks are in place; only a certificate is missing.

Route decision (July 2026): Azure Artifact Signing is excluded — its
individual-developer identity validation covers the USA/Canada only.
Certum's Open Source certificate (~$58/yr, SimplySign cloud, worldwide,
signtool-compatible) works today with a private repo. **SignPath
Foundation** signs OSS projects for free but requires a public repo and an
application review — since going public is already on this checklist, the
certificate is deferred until then, with SignPath as the intended route.

To enable signing with a signtool-shaped certificate (Certum, Azure):

```sh
IAHELPER_SIGN_ARGS='/sha1 <cert-thumbprint> /fd sha256 /tr http://time.certum.pl /td sha256' \
    bash build-aux/windows/build.sh
```

That signs `ia-helper.exe` and the bundled `gdk-pixbuf-query-loaders.exe`
(the two PE executables — leaving the ~120 DLLs unsigned is normal
practice), has Inno sign the installer *and* uninstaller, and runs
`signtool verify /pa` on the result. `signtool verify /pa` on any shipped
exe is the check that flips from red to green once this is live.

Caveats: the SignPath route signs through their platform (typically a
GitHub Actions integration), bypassing these local hooks — the release
flow would move to CI at that point. The portable ZIP itself cannot be
Authenticode-signed; the exe inside it is, and SHA256SUMS covers the
archive. Note an OV certificate does not silence SmartScreen instantly —
reputation accrues per-certificate as downloads accumulate.
