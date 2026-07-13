# IA Helper — Architecture

## The one rule

**`core/` never imports GTK; `ui/` never talks to archive.org directly.**

Everything else follows from this split: the archive.org logic is portable
(future Windows port, potential CLI reuse) and unit-testable without a
display server or network, while the UI layer stays a thin GTK4/libadwaita
shell. Libadwaita use is deliberately confined to window chrome
(`ApplicationWindow`, `HeaderBar`, `NavigationView`, `ViewStack`, toasts,
status pages, dialogs) so a Windows build could swap it for plain GTK
without touching behavior.

## Module map

```
ia_helper/
  core/                    GTK-free; blocking calls, meant for worker threads
    api.py                 shared ArchiveSession: User-Agent, 429/5xx retry
                           with backoff, connection budget
    search.py              advancedsearch.php client; SearchQuery builder;
                           SearchResult/SearchPage dataclasses
    items.py               Item Metadata API: ItemDetails, FileEntry
                           (private/DRM flags), simple-list memberships,
                           HTML→text description reduction
    thumbnails.py          thumbnail fetch: 2-worker pool, disk cache,
                           generation counter + cancellable futures
    downloads.py           DownloadManager: queue, bounded workers, Range
                           resume, streaming MD5 verify, JSON persistence
    account.py             sign-in via internetarchive.configure() (S3 keys;
                           password never stored), check_auth who-am-i,
                           sign-out (credential sections removed from ia.ini)
    config.py              Config dataclass; JSON load/save under XDG paths
  ui/                      GTK4/libadwaita; no direct archive.org access
    window.py              MainWindow: NavigationView (root ⇄ item pages),
                           Search/Downloads ViewStack, app menu, actions,
                           shared session/client construction, About
    search_view.py         query entry + mediatype filter, ListView results,
                           paging, error/retry page, thumbnail lifecycle
    item_view.py           item page: metadata header, restriction banner,
                           "Member of" chips, uploader link, file ColumnView
                           with selection rules
    downloads_view.py      live queue list; trampolines manager events onto
                           the main loop
    settings.py            Adw.PreferencesDialog: download dir, concurrency
    format.py              size formatting
    worker.py              run_in_thread(): worker thread → GLib.idle_add
  main.py                  Adw.Application: actions, accelerators, --version
```

## Threading model

GTK owns the main loop; nothing in `core/` may run on it.

- **One-shot calls** (search pages, item metadata): `ui/worker.py`
  `run_in_thread(func, on_success, on_error)` runs the blocking call on a
  daemon thread and delivers the result via `GLib.idle_add`, so callbacks
  are safe to touch widgets. A monotonic token in the search view discards
  results of superseded searches.
- **Thumbnails**: a 2-worker `ThreadPoolExecutor` in core. Two cancellation
  mechanisms exist because list rows are recycled: a *generation counter*
  invalidates everything queued for a previous search, and the returned
  *futures* are cancelled by the UI when a row is unbound/recycled — the
  queue only ever holds fetches for rows on screen. Both were added to fix
  real observed stalls (minutes of backlog on large collections).
- **Downloads**: `DownloadManager` spawns one daemon thread per running
  task, capacity-gated by counting RUNNING tasks under an RLock
  (`_maybe_start`). Pause/cancel are per-task `threading.Event`s checked
  each chunk. Manager listeners fire **on worker threads**; the downloads
  view trampolines every event through `GLib.idle_add` before touching
  widgets, updating rows via a `rev` property that bound rows watch.

## Data flow (typical journey)

```
search entry ──▶ SearchClient.search()  (worker thread)
                    advancedsearch.php, rows=50, page=N
             ◀── SearchPage → Gio.ListStore → Gtk.ListView (recycled rows)
row activate ──▶ ItemClient.get_item()  (worker thread)
                    /metadata/<id>  (one call: metadata + files + flags)
                    /metadata/<id>/simplelists  (lazy, optional)
"Download"  ──▶ DownloadManager.enqueue(identifier, [FileEntry…])
                    /download/<id>/<file>  streaming → .part → verify → rename
```

Grouping chips (collection, simple list, uploader) all route back through
`MainWindow.browse_query()`, which places the raw query in the search entry
— one search path, no special modes.

## archive.org API surface

| Endpoint | Used for |
|---|---|
| `advancedsearch.php` | all searching/browsing (paged; called directly rather than via `internetarchive.search_items()`, which silently switches APIs based on params) |
| `/metadata/<id>` | full item record in one call |
| `/metadata/<id>/simplelists` | list memberships (`{list: {parent: …}}`) |
| `/services/img/<id>` | thumbnails |
| `/download/<id>/<file>` | file downloads (Range supported) |

The `internetarchive` library provides the session (`get_session()`),
which reads stored account keys from the standard `ia` config file — after
sign-in/out the window builds a fresh session and hands it to every holder
(`_adopt_session`), so authentication is app-wide without restarting.
Who-am-i goes to `s3.us.archive.org?check_auth=1` (the library's own
mechanism), which maps keys to the email and the `@itemname` that keys the
`fav-*` favorites pseudo-collection. Citizenship policies (User-Agent,
backoff on 429/5xx honoring Retry-After, connection budget) are configured
once in `core/api.py`, not per feature.

## Persistence

| File | Contents |
|---|---|
| `~/.config/ia-helper/config.json` | download dir, max concurrent downloads |
| `~/.local/state/ia-helper/queue.json` | download queue (no progress ticks — progress recovers from `.part` sizes on load; RUNNING re-queues) |
| `~/.cache/ia-helper/thumbnails/` | thumbnail bytes keyed by identifier |

Plain JSON rather than GSettings is deliberate: no schema compilation, and
identical behavior in a venv, a .deb, a Flatpak, and a future Windows build.

## Download integrity

Files stream to `<dest>.part` while an MD5 is computed incrementally; on
resume the existing partial is rehashed first, so the digest always covers
the whole file. The `.part` is renamed to its final name only after size
and checksum verification — the filesystem never contains a final-named
file that isn't verified. A server that ignores a Range request (HTTP 200)
triggers a clean restart; HTTP 416 with a full-sized partial finalizes it.

## Restriction handling

Three independent signals, all parsed in `core/items.py`:

- `is_dark` (record level) → item view shows an error page.
- `access-restricted-item` metadata flag / `nodownload` → banner + search
  result label; informational, since restriction is actually per-file.
- per-file `private` → unselectable in the UI **and** refused by
  `DownloadManager.enqueue()`, so no code path can queue a guaranteed 403.
- DRM lending containers (format contains "Encrypted") are public by
  design: labelled, skipped by Select-all, individually downloadable.

## Testing strategy

`tests/` runs with `python -m unittest discover tests` — no GTK, no
network, sub-second. The download engine is exercised end-to-end through a
fake requests-shaped session (happy path, Range resume, ignored Range, 416
finalization, checksum failure, path safety, persistence round-trips);
thumbnails likewise (cache hits, generation drops, future cancellation)
using a blocking session to make race-order deterministic. API parsing is
pinned against payload shapes captured from live archive.org responses.
UI behavior is verified manually on a Linux VM (see README for the flow).
