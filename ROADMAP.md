# IA Helper — Roadmap

## Completed (MVP)

| Milestone | Delivered |
|---|---|
| M1 | Walking skeleton: window, live search with mediatype filter, thumbnails, paging |
| M2 | Item view: metadata, file list with selection, "Member of" collections and simple lists, collection browsing |
| M3 | Download manager: queue, bounded workers, pause/resume/cancel/retry, Range resume, MD5 verification, persistence, preferences |
| M4 | Packaging: Flatpak with pinned offline dependencies; Debian packaging (Ubuntu 26.04+) |
| M5 | Polish: app menu, About/version, keyboard shortcuts, search error/retry states, 429/5xx backoff, chip styling |
| M6 | IA account login (S3 keys via `ia configure`, My favorites / My uploads, entitled downloads) and search sorting |

Post-MVP additions along the way: access-restriction handling
(lending-library items, private files), DRM labelling with Select-all
exclusion, uploader grouping, thumbnail queue cancellation fixes.

## Before first public release

Non-code items, in rough order:

1. **License** — currently GPL-3.0-or-later as a placeholder in the
   metainfo and `debian/copyright`; decide, add a `LICENSE` file, sync all
   three.
2. **Icon** — replace the placeholder SVG in
   `data/icons/hicolor/scalable/apps/`.
3. **Screenshots** — take on the VM, host at stable URLs, add
   `<screenshots>` to the metainfo (Flathub requires them).
4. **Repo public** — required for Flathub app-ID verification
   (`io.github.stargazernz.IAHelper` ⇄ github.com/stargazerNZ/ia_helper).
5. **Flathub submission** — run `appstreamcli validate` and
   `desktop-file-validate` clean first.

## Future development candidates

Ordered roughly by value-for-effort; none are commitments.

### Grouped downloads view
The queue is a flat per-file list; downloading 40 files from one item
shows 40 rows. Group rows by item with an expander and per-item aggregate
progress/actions.

### Query-based bulk downloads ("sets of items")
The deliberately parked MVP feature: "download everything matching this
query/collection". Needs the Scrape API (cursor-based, for result sets
beyond advanced search's ~10k window), a mandatory size-preview
confirmation step before queueing (items can be hundreds of GB), and
probably per-item file-type filters (e.g. originals only). The biggest
IA-citizenship surface in the app — design the throttling first.

### Search improvements
A date-range filter and a field-query builder for users who don't know
Lucene syntax.

### Downloads QoL
Optional bandwidth limit; desktop notification on queue completion;
re-verify a completed file on demand.

### Windows port
The core module is already portable (pathlib, no GTK, JSON persistence).
Needs: GTK4/PyGObject via MSYS2 or gvsbuild, a decision on libadwaita vs
plain-GTK chrome (the chrome is isolated for exactly this), Windows paths
for config/state/cache (XDG fallbacks currently assume Unix), and an
installer (MSYS2 packaging or WiX). The `.part`-rename and path-safety
logic already anticipates NTFS constraints (drive-colon rejection).

### Item view extras
Inline preview for images/audio where formats allow; related-items
section; richer description rendering (currently HTML is flattened to
plain text).

## Maintenance notes

- Flatpak dependency pins: regenerate with
  `python3 build-aux/flatpak/update-python-deps.py` when the
  `internetarchive` tree changes; review the printed pins and commit.
- The GNOME runtime version in the manifest (currently 48) needs a bump
  roughly yearly as runtimes go EOL.
- API behavior (restriction flags, simple-list shapes) was verified against
  live archive.org responses at development time; the payload-shape tests
  in `tests/` are the canary if IA changes anything.
