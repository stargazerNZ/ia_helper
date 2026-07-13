# IA Helper

A GTK4/libadwaita application that simplifies searching for and downloading
items, collections, and lists from the [Internet Archive](https://archive.org),
operating within the Archive's
[guidelines for automated access](https://archive.org/developers/index-apis.html):
it identifies itself, limits concurrent connections, backs off when asked,
verifies downloads against published checksums, and honors access
restrictions on lending material.

**Status:** MVP complete plus account integration (v0.6.x). See
[ROADMAP.md](ROADMAP.md) for what's next.

## Documentation

| Document | Contents |
|---|---|
| [REQUIREMENTS.md](REQUIREMENTS.md) | What the application does and the rules it follows |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Code structure, threading model, API usage, design decisions |
| [ROADMAP.md](ROADMAP.md) | Completed milestones, pre-release checklist, future candidates |

## Running (development, Linux)

```sh
# Debian/Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -e .
python -m ia_helper
```

`--system-site-packages` lets the venv see the distro's PyGObject; only
`internetarchive` comes from pip. Note: Python venvs cannot live on VM
shared folders (no symlink support) — clone to a native filesystem.

## Tests

Core-module tests need no GTK, no network, and run anywhere:

```sh
python -m unittest discover tests
```

## Building the Flatpak

Dependencies are pinned in the committed
`build-aux/flatpak/python3-internetarchive.json`
(regenerate with `python3 build-aux/flatpak/update-python-deps.py` when
they change), so the build works from a clean clone:

```sh
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.gnome.Platform//48 org.gnome.Sdk//48

flatpak-builder --user --install --force-clean flatpak-build \
    build-aux/flatpak/io.github.stargazernz.IAHelper.json
flatpak run io.github.stargazernz.IAHelper
```

Sandbox permissions: network, `xdg-download`, and display/GPU sockets —
nothing else.

## Building the .deb

Debian packaging lives in `debian/` (native package, targets Ubuntu 26.04+
where `python3-internetarchive` is in universe):

```sh
sudo apt install devscripts debhelper dh-python python3-all \
    python3-setuptools pybuild-plugin-pyproject
dpkg-buildpackage -us -uc -b
sudo apt install ../ia-helper_*.deb
```

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+F | Focus the search entry |
| Ctrl+1 / Ctrl+2 | Switch to Search / Downloads |
| Ctrl+, | Preferences |
| Ctrl+Q | Quit (persists the download queue) |
| Alt+←, swipe, mouse back | Back from an item page |
