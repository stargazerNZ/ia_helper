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
| M7 | Grouped downloads view: expander per item with aggregate progress and group pause/resume/cancel/open-folder |
| M8 | Query-based bulk downloads: Scrape API survey + size confirmation, self-pacing feeder, restriction-aware, resumable |

Post-MVP additions along the way: access-restriction handling
(lending-library items, private files), DRM labelling with Select-all
exclusion, uploader grouping, thumbnail queue cancellation fixes.

## Before first public release

See [RELEASING.md](RELEASING.md) for the full ordered procedure. Status:

1. **License** ✓ — GPL-3.0-or-later; LICENSE file added, metainfo,
   debian/copyright, and pyproject in sync.
2. **Icon** ✓ — redrawn flat SVG (replaceable later without ceremony).
3. **Screenshots** — take on the VM per RELEASING.md §1; metainfo slots
   are wired to `data/screenshots/*.png`.
4. **Repo public** — GitHub settings; required for Flathub app-ID
   verification and screenshot URLs.
5. **Tag v1.0.0 and submit to Flathub** — manifest ready in
   `build-aux/flathub/`; validate first (RELEASING.md §2, §6–7).

## Future development candidates

Ordered roughly by value-for-effort; none are commitments.

### Bulk download refinements
Shipped in M8 (plus format filters and cancel propagation); possible
follow-ons: a bandwidth ceiling while a bulk job runs, surfacing per-item
failures for later retry, and per-format size estimates (would need a
metadata crawl, so probably sampling-based).

### Search improvements
A date-range filter and a field-query builder for users who don't know
Lucene syntax. The controls row is near capacity (entry, mediatype,
language, sort, search, bulk) — the next filter added should move the
filters into a popover.

### Downloads QoL
Optional bandwidth limit; desktop notification on queue completion;
re-verify a completed file on demand.

### Windows port — shipped (1.3.1)
Runs via MSYS2 GTK4 + libadwaita; platform-aware app dirs and NTFS-safe
file names landed in 1.3.1, and releases now carry an NSIS per-user
installer plus a portable ZIP (built by `build-aux/windows/build.sh` —
PyInstaller with explicit GTK collection; see the spec for the two
build-machine traps it defuses: Git-for-Windows' GLib shadowing PATH
resolution, and system DLLs leaking into the bundle). Account sign-in verified
on Windows (2026-07-16). Code signing: build hooks are in place
(`IAHELPER_SIGN_ARGS`, see RELEASING.md) but the certificate is deferred
until the repo goes public — SignPath Foundation (free for OSS, requires
public repo) is the intended route; Azure is unavailable to individuals
outside USA/Canada. Remaining polish: bundle an emoji font (Pango
fallback warnings) and decide whether Adwaita styling on Windows warrants
a plain-GTK chrome variant.

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
