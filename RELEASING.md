# Releasing IA Helper

Ordered steps for the first public release (v1.0.0). Later releases reuse
steps 4–8 with a new version.

## 1. Screenshots (on the Linux VM)

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

## 2. Validate (on the VM)

```sh
desktop-file-validate data/io.github.stargazernz.IAHelper.desktop
appstreamcli validate data/io.github.stargazernz.IAHelper.metainfo.xml
```

`appstreamcli` warns about unreachable screenshot URLs until the repo is
public — that specific warning is expected at this stage; anything else
should be fixed.

## 3. Make the repository public

GitHub → Settings → General → Danger Zone → Change visibility. Required
for Flathub verification (app ID `io.github.stargazernz.IAHelper` must
match the public repo) and for the screenshot URLs to resolve.

## 4. Final version check

`ia_helper/__init__.py`, `pyproject.toml`, the metainfo `<release>` list,
and `debian/changelog` should all agree on the version being released.

## 5. Tag

```sh
git tag -a v1.0.0 -m "IA Helper 1.0.0"
git push origin v1.0.0
```

## 6. Verify the Flathub manifest builds

The submission manifest is `build-aux/flathub/io.github.stargazernz.IAHelper.json`
(identical to the local one except it builds from the git tag, not the
working directory). Test it on the VM:

```sh
cp build-aux/flatpak/python3-internetarchive.json build-aux/flathub/
flatpak-builder --user --install --force-clean flathub-build \
    build-aux/flathub/io.github.stargazernz.IAHelper.json
flatpak run io.github.stargazernz.IAHelper
```

## 7. Submit to Flathub

Follow https://docs.flathub.org/docs/for-app-authors/submission:
fork `flathub/flathub`, create a branch named `io.github.stargazernz.IAHelper`
from the `new-pr` base branch, add two files at the repo root —
`io.github.stargazernz.IAHelper.json` (the flathub manifest) and
`python3-internetarchive.json` — and open a PR against `new-pr`.
Respond to reviewer feedback; once merged, Flathub creates the app repo
and the build goes live.

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

## 8. After acceptance

- Announce/link the Flathub page in the README.
- Subsequent releases: bump versions, add a metainfo `<release>`, tag, and
  update the tag in the Flathub app repo (a PR against
  `flathub/io.github.stargazernz.IAHelper`).
