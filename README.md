# IA Helper

A GTK4/libadwaita application that simplifies searching for and downloading
items, collections, and lists from the [Internet Archive](https://archive.org),
operating within the Archive's
[guidelines for automated access](https://archive.org/developers/index-apis.html):
it identifies itself with a descriptive User-Agent, limits concurrent
connections, and caches thumbnails and metadata locally.

**Status: Milestone 5** — polish. The MVP feature set is complete.

## Roadmap

| Milestone | Scope |
|---|---|
| M1 ✓ | Walking skeleton: window, search, results list, thumbnails, paging |
| M2 ✓ | Item view: metadata, file list with selection, "Member of" collections/lists |
| M3 ✓ | Download manager: queue, progress, pause/resume, checksum verification |
| M4 ✓ | Packaging: Flatpak (primary), .deb (secondary) |
| **M5 (this)** | Polish: app menu/About, shortcuts, error states, rate-limit backoff |

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+F | Focus the search entry (jumps to the Search view) |
| Ctrl+1 / Ctrl+2 | Switch to Search / Downloads |
| Ctrl+, | Preferences |
| Ctrl+Q | Quit (persists the download queue) |
| Alt+←, swipe, mouse back | Back from an item page (built into NavigationView) |

Parked for post-MVP: query-based "sets of items" bulk downloads (Scrape API),
uploads, metadata editing, Wayback Machine features.

## Architecture

```
ia_helper/
  core/          # archive.org logic — NO GTK imports; portable + testable
    api.py         # shared session, User-Agent, connection budget
    search.py      # advancedsearch.php client, query builder (collections,
                   # simple lists, favorites are all just query forms)
    items.py       # Item Metadata API: full record, file list, simplelists
    thumbnails.py  # thumbnail fetch + on-disk cache
    downloads.py   # download queue: workers, Range resume, MD5 verify,
                   # persistence (~/.local/state/ia-helper/queue.json)
    config.py      # settings JSON (~/.config/ia-helper/config.json)
  ui/            # GTK4/libadwaita — libadwaita kept to layout chrome only,
                 # so a future Windows build can swap it out
    window.py      # NavigationView + Search/Downloads ViewStack, shared clients
    search_view.py
    item_view.py   # metadata, "Member of" chips, file list with selection
    downloads_view.py
    settings.py    # preferences dialog (download dir, concurrency)
    format.py
    worker.py      # thread → GLib.idle_add bridge
  main.py        # Adw.Application entry point
```

IA groupings the app understands (all resolve to search queries):

- **Collections** — `collection:<id>`; hierarchical (collections nest).
- **Simple lists** — `simplelists__<list>:<parent>`; an item's memberships
  come from `GET /metadata/<id>/simplelists`.
- **Favorites** — the pseudo-collection `collection:fav-<username>`.
- **Uploader** — `uploader:"<email>"`; shown as a clickable "Uploaded by"
  link on the item page (absent on many institutional/scanned items).

## Downloads

Access-restricted items (the `access-restricted-item` flag — e.g. controlled
digital lending books) are labelled in search results and get a banner on the
item page; their `private` files are shown but cannot be selected, and the
download manager refuses to queue them. This honors the Archive's terms for
lending material — such items can be borrowed on archive.org, not downloaded.

Files download to `<download dir>/<identifier>/<file>` (default: your XDG
download directory), streaming into a `.part` file that is renamed into place
only after the size and MD5 checks pass. Interrupted downloads resume with
HTTP Range requests. The queue survives restarts; tasks that were mid-flight
re-queue automatically. Concurrency is user-configurable but hard-capped at 5
out of politeness to archive.org.

## Running (development, Linux)

```sh
# Debian/Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita

python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -e .
python -m ia_helper
```

`--system-site-packages` lets the venv see the distro's PyGObject; only
`internetarchive` comes from pip.

## Tests

Core-module tests need no GTK, no network, and run anywhere:

```sh
python -m unittest discover tests
```

## Building the Flatpak

The manifest is [build-aux/flatpak/io.github.stargazernz.IAHelper.json](build-aux/flatpak/io.github.stargazernz.IAHelper.json);
the Python dependencies are pinned in the committed
`python3-internetarchive.json` module (regenerate with
`python3 build-aux/flatpak/update-python-deps.py` when deps change), so the
build works out of the box:

```sh
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.gnome.Platform//48 org.gnome.Sdk//48

flatpak-builder --user --install --force-clean flatpak-build \
    build-aux/flatpak/io.github.stargazernz.IAHelper.json
flatpak run io.github.stargazernz.IAHelper
```

Sandbox permissions requested: network, `xdg-download` (default download
location), and display/GPU sockets — nothing else.

## Building the .deb

Debian packaging lives in `debian/` (native package, targets Ubuntu 26.04+
where `python3-internetarchive` is in universe):

```sh
sudo apt install devscripts debhelper dh-python python3-all \
    python3-setuptools pybuild-plugin-pyproject
dpkg-buildpackage -us -uc -b
sudo apt install ../ia-helper_*.deb
```

## Error handling

The shared session retries GETs with exponential backoff on HTTP 429 and
5xx, honoring `Retry-After` — per the Archive's automated-access
guidelines. A failed first search page shows a Retry page; a failed "Load
more" keeps existing results and toasts. Mid-download failures surface in
the queue and resume with a Range request on retry.

## Before publishing

- [ ] Confirm the app ID (`io.github.stargazernz.IAHelper` assumes the code
      lives at github.com/stargazerNZ/ia_helper) — it must match your repo
      host for Flathub verification.
- [ ] Choose a license (metainfo and debian/copyright currently say
      GPL-3.0-or-later as a placeholder; add a LICENSE file to match).
- [ ] Replace the placeholder icon in `data/icons/`.
- [ ] Add screenshots to the metainfo (required for Flathub).
