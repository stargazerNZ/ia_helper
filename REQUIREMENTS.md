# IA Helper — Requirements

IA Helper is a desktop application that simplifies searching for and
downloading items, collections, and lists from the
[Internet Archive](https://archive.org), while operating strictly within the
Archive's terms of service and
[automated-access guidelines](https://archive.org/developers/index-apis.html).

"Must" requirements are implemented in the MVP; anything aspirational lives
in [ROADMAP.md](ROADMAP.md).

## 1. Search and browsing

- **R1.1** The user must be able to search the Archive by free text, with an
  optional media-type filter (texts, movies, audio, image, software, data,
  collection).
- **R1.2** Results must show thumbnail, title, creator, date, media type,
  identifier, and item size, and must page incrementally ("Load more")
  rather than fetching unbounded result sets.
- **R1.3** Raw Lucene queries typed into the search box must work as-is
  (e.g. `collection:prelinger`), so every grouping below is also reachable
  by hand.
- **R1.4** Access-restricted items must be labelled directly in search
  results (see R4).
- **R1.5** Results must be sortable: relevance (default), most downloaded,
  date (newest/oldest), recently added, title A–Z. Changing sort re-runs
  the active search.
- **R1.6** A language filter must be offered (server-side query
  refinement, so it composes with paging, sorting, and bulk downloads).
  Because IA language metadata mixes MARC codes, ISO codes, and names,
  each curated language ORs its known variants; because the metadata is
  sparse, filtering excludes unlabelled items — a documented limitation.
  Filter changes apply to the active search immediately.

## 2. Item view

- **R2.1** Activating a result must show the item's full metadata: title,
  creator, date, media type, size, file count, description (HTML reduced to
  plain text), and thumbnail.
- **R2.2** The complete file list must be shown with per-file format, size,
  and origin (original/derivative/metadata), with an "original files only"
  filter.
- **R2.3** Files must be individually selectable, with select all/none and a
  live "N files selected · total size" summary.
- **R2.4** Dark items (`is_dark`) must show an explanatory error page, not a
  broken item view.

## 3. Groupings

All Archive groupings resolve to search queries; the app must expose each as
a one-click navigation that places the visible, editable query in the search
box:

- **R3.1 Collections** — `collection:<id>`; membership chips on the item
  page; collections themselves offer "Browse this collection". Collections
  nest, so a result that is itself a collection must be browsable.
- **R3.2 Simple lists** — `simplelists__<list>:<parent>`; memberships come
  from `GET /metadata/<id>/simplelists` and are shown as list chips.
- **R3.3 Uploader** — `uploader:"<email>"`; a clickable "Uploaded by" link
  on the item page whenever the metadata carries the field.
- **R3.4 Favorites** — the pseudo-collection `collection:fav-<itemname>`;
  a "My favorites" menu entry when signed in (see R9), and reachable by
  hand via R1.3.

## 4. Access restrictions (terms-of-service compliance)

- **R4.1** Items flagged `access-restricted-item` (e.g. controlled digital
  lending books) must be labelled in search results and carry a banner on
  the item page explaining they can be borrowed on archive.org, not
  downloaded.
- **R4.2** Files marked `private` must be visible but unselectable and must
  be refused by the download queue even if a code path submits one
  (defense in depth) — never "try and 403".
- **R4.3** DRM-protected lending containers (ACS/LCP encrypted PDF/EPUB)
  are public by design and must stay downloadable, but must be labelled
  ("· DRM" plus tooltip) and excluded from "Select all"; an explicit
  individual tick still selects them.

## 5. Downloads

- **R5.1** Selected files must download to
  `<download dir>/<identifier>/<file path>`, preserving subdirectories in
  file names while rejecting unsafe paths (absolute, `..`, drive colons).
- **R5.2** Downloads must stream to a `.part` file renamed into place only
  after size and (when published) MD5 verification pass — a partial or
  corrupt file must never masquerade as complete.
- **R5.3** Interrupted downloads must resume via HTTP Range, rehashing the
  existing partial so verification stays valid; a server that ignores Range
  must trigger a clean restart.
- **R5.4** The queue must support pause, resume, cancel (removing the
  partial), retry of failures, and "clear finished".
- **R5.5** The queue must persist across restarts; tasks mid-flight at exit
  re-queue automatically, recovering progress from `.part` sizes.
- **R5.6** Already-complete files must be detected at enqueue time and not
  re-downloaded; duplicate active queue entries must be refused.
- **R5.7** Download progress must show per-task progress, speed, and state,
  with an "open containing folder" action for completed files.
- **R5.8** The downloads view must group tasks by item (title, aggregate
  file count/size/progress) with group-level pause/resume/cancel and an
  "open item folder" action; per-file controls remain inside each group.

## 6. Internet Archive citizenship

- **R6.1** Every request must carry a descriptive User-Agent naming the app,
  version, and project URL.
- **R6.2** Concurrency must stay modest: one search/metadata request, two
  thumbnail workers, and 1–5 concurrent downloads (default 3, hard cap 5,
  user-configurable).
- **R6.3** GETs must retry with exponential backoff on HTTP 429/5xx and
  honor `Retry-After`.
- **R6.4** Thumbnails must be cached on disk; browsing must not re-fetch
  what has already been fetched.
- **R6.5** Work the user can no longer see must be cancelled: pending
  thumbnail fetches are dropped on a new search and when their row scrolls
  off screen.

## 7. Application shell

- **R7.1** Preferences: download directory (folder picker) and download
  concurrency, persisted as JSON.
- **R7.2** Keyboard shortcuts: Ctrl+F focus search, Ctrl+1/Ctrl+2 view
  switching, Ctrl+, preferences, Ctrl+Q quit-with-persistence.
- **R7.3** An About dialog showing the running version; `--version` on the
  command line.
- **R7.4** Failures must be survivable: first-page search errors show a
  retry page, partial failures toast without destroying state, and the app
  must never crash on network loss.

## 8. Platform and packaging

- **R8.1** Linux with GTK4 + libadwaita is the primary target; Flatpak is
  the primary distribution (GNOME 48 runtime, sandbox limited to network,
  `xdg-download`, and display/GPU), with a Debian package secondary
  (Ubuntu 26.04+).
- **R8.2** A future Windows port must remain feasible: all archive.org
  logic lives in a GTK-free core module, and libadwaita use is confined to
  swappable window chrome.
- **R8.3** Core logic must be unit-testable without network access or a
  display server.

## 9. Account integration

- **R9.1** The user must be able to sign in with their archive.org email
  and password from Preferences. The password must be used once — exchanged
  for S3-style API keys stored in the standard `ia` config file — and never
  persisted or logged.
- **R9.2** Signed-in state must be shown in Preferences ("Signed in as …")
  and must survive restarts (keys re-read at startup; the account resolved
  without network when no keys exist).
- **R9.3** Sign-out must remove the stored credentials (the `[s3]` and
  `[cookies]` config sections) while preserving unrelated `ia` settings.
- **R9.4** When signed in, "My favorites" and "My uploads" must be one
  click away (main menu), and all requests carry the account's keys so
  entitled files download. Signing in must not weaken R4 in any way —
  restriction handling is unchanged.

## 10. Bulk downloads

- **R10.1** The user must be able to bulk-download everything matching the
  current search query (collections and uploaders being the primary
  cases), via the Scrape API for result sets beyond advanced search's
  pagination window.
- **R10.2** Nothing may be queued before the user confirms a survey
  showing the item count and total size (IA collections routinely measure
  terabytes). Queries beyond 20,000 items must be refused with a prompt to
  refine.
- **R10.3** Bulk jobs must self-pace: at most one metadata fetch in
  flight, feeding the download queue only as it drains (never flooding
  the queue, the queue file, or the API). The finished-task history must
  be pruned so thousands of files can stream through a bounded queue.
- **R10.4** Restriction policy is unchanged in bulk (R4): restricted
  items are skipped via the search-side flag without even fetching their
  metadata; private files and DRM containers are excluded per item.
- **R10.5** Bulk jobs must be pausable, cancellable, and resumable —
  including across restarts, where they restore as PAUSED (a
  multi-terabyte mistake must need a human click to continue) and resume
  without re-fetching metadata for items already processed. Files already
  on disk are skipped silently.
- **R10.6** File selection modes: all files, original files only (default
  — derivatives are usually bulk noise), or specific formats chosen from a
  checklist harvested during the survey (per-format item counts shown, so
  partial coverage across a mixed collection is visible before
  confirming). Format matching uses IA's canonical format names, never
  file extensions.

## Out of scope for the MVP

Uploads, metadata editing, reviews, and Wayback Machine features — see
[ROADMAP.md](ROADMAP.md).
