# Releasing IA Helper

Two separate things live in this document: the **GitHub release
procedure** (automated since 2026-07-22 by
[`.github/workflows/release.yml`](.github/workflows/release.yml); v1.0.0
through v1.3.3 were built by hand before that — see `ia_helper/__init__.py`
for the current version) and the **going-public / Flathub checklist**
(still pending — the repo is private and the app isn't on Flathub yet).

## GitHub release procedure (repeat for every version)

1. **Bump the version** in `ia_helper/__init__.py`, `pyproject.toml`, add
   a `<release>` entry to the metainfo, and add a `debian/changelog`
   entry. Commit and push to `main`.
2. **Tag and push**: `git tag -a vX.Y.Z -m "IA Helper X.Y.Z"` then
   `git push origin vX.Y.Z`. This triggers the `Release` workflow, which:
   - refuses to proceed if the tag doesn't match `__init__.py`'s
     `__version__` (catches a forgotten version bump before anything
     builds);
   - runs the test suite;
   - builds the `.deb` and Flatpak bundle on an Ubuntu runner, and
     installs each to confirm `--version`/`dpkg -I` before uploading;
   - builds the Windows installer and portable ZIP on a Windows runner
     via MSYS2 (mirroring `build-aux/windows/build.sh` exactly), then
     runs the **same silent install/launch/uninstall cycle** that once
     caught a real bug (Inno Setup leaving a previous version's files
     behind on upgrade; see ROADMAP.md) as an automated gate rather than
     a manual step;
   - computes a combined `SHA256SUMS` and opens the release as a
     **draft** with all four artifacts attached.
3. **Review and publish**: check the Actions run, open the draft release
   under the repo's Releases tab, edit the auto-generated notes if
   wanted, and click Publish. Nothing goes out without this manual step.

Re-running: `workflow_dispatch` (Actions tab → Release → Run workflow)
takes an existing tag name and repeats the whole pipeline — useful if a
runner-side step failed transiently (e.g. a flaky Flathub mirror) without
needing a new tag.

`gh release view --json ... /releases/tags/vX.Y.Z` is occasionally flaky
(GitHub's "Unicorn" transient-error page) even when the release itself is
fine — if so, verify via `gh api repos/.../releases` (list, not
tag-lookup) and `gh api repos/.../releases/<id>/assets` instead.

Before the workflow existed, this was a fully manual recipe combining a
local WSL Ubuntu clone (Linux artifacts) and MSYS2 on the same Windows box
(Windows artifacts) — kept here in case the workflow ever needs local
debugging, since the job steps are a direct translation of these commands:

<details>
<summary>Manual recipe (superseded by the workflow, kept for reference)</summary>

```sh
# Linux artifacts, in a WSL Ubuntu clone (~/ia_helper-release):
cd ~/ia_helper-release && git fetch -q origin && git checkout vX.Y.Z
dpkg-buildpackage -us -uc -b
flatpak-builder --user --force-clean --repo=flatpak-repo flatpak-build \
    build-aux/flatpak/io.github.stargazernz.IAHelper.json
flatpak build-bundle flatpak-repo io.github.stargazernz.IAHelper-X.Y.Z.flatpak \
    io.github.stargazernz.IAHelper --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo
```

```sh
# Windows artifacts, from an MSYS2-capable shell:
bash build-aux/windows/build.sh   # console smoke test, windowed build, installer
```
Then zip the portable tree:
`Compress-Archive -Path build-aux\windows\dist\ia-helper\* -DestinationPath ia-helper-X.Y.Z-windows-x64-portable.zip`,
and run the silent install/launch/uninstall cycle:
```powershell
.\ia-helper-X.Y.Z-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES
& "$env:LOCALAPPDATA\Programs\IA Helper\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
```

```sh
sha256sum *.deb *.flatpak *-setup.exe *-portable.zip > SHA256SUMS
gh release create vX.Y.Z --title "IA Helper X.Y.Z" --notes-file notes.md \
    ia-helper_X.Y.Z_all.deb io.github.stargazernz.IAHelper-X.Y.Z.flatpak \
    ia-helper-X.Y.Z-windows-x64-setup.exe ia-helper-X.Y.Z-windows-x64-portable.zip \
    SHA256SUMS --repo stargazerNZ/ia_helper
```

</details>

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
