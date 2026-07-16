"""IA Scrape API client: exhaustive result sets for bulk downloads.

Advanced search caps deep pagination (~10k); the Scrape API
(/services/search/v1/scrape) walks arbitrarily large result sets with a
cursor. Two live-verified quirks shape this client:

  - Never send ``count``: with count=100 the cursor silently fails to
    advance (the same first page repeats forever). Omitting it uses the
    5000-item default, which pages correctly and suits bulk anyway.
  - The ``total`` field is only authoritative on the FIRST page; later
    pages report the remainder.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from urllib.parse import urlencode

SCRAPE_URL = "https://archive.org/services/search/v1/scrape"
SURVEY_FIELDS = "identifier,item_size,access-restricted-item,format"

# Machinery formats: real files, but rarely what a bulk download is after.
# The dialog ranks these below content formats. (Names are IA-canonical —
# the same strings appear in the search index and item file metadata.)
NOISE_FORMATS = frozenset({
    "Metadata",
    "Item Tile",
    "Archive BitTorrent",
    "Scandata",
    "DjVuTXT",
    "Djvu XML",
    "chOCR",
    "hOCR",
    "OCR Page Index",
    "OCR Search Text",
    "Page Numbers JSON",
    "Abbyy GZ",
    "Single Page Processed JP2 ZIP",
    "Single Page Processed JP2 Tar",
    "Single Page Processed JPEG ZIP",
    "Single Page Processed JPEG Tar",
    "MARC",
    "MARC Source",
    "MARC Binary",
    "Dublin Core",
    "Metadata Log",
    "Columbia Peaks",
    "Spectrogram",
    "Essentia High GZ",
    "Essentia Low GZ",
    "JSON",
    "Log",
    "Backup ITEM_META",
    "Web ARChive GZ",
    "CDX Index",
    "Item CDX Index",
    "Item CDX Meta-Index",
    "WARC CDX Index",
})

# Citizenship guardrail: refuse bulk jobs beyond this many items (also caps
# survey traffic — 4 scrape requests). "Download half the Archive" queries
# should be refined, not attempted.
MAX_BULK_ITEMS = 20_000


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


@dataclass
class ScrapeItem:
    identifier: str
    item_size: int = 0
    access_restricted: bool = False
    # File formats the item contains, per the search index.
    formats: list[str] = field(default_factory=list)


@dataclass
class Survey:
    """What a bulk download would cover, measured before any confirmation."""

    items: int = 0
    total_bytes: int = 0
    restricted: int = 0
    # format -> number of items containing at least one file of it.
    formats: dict[str, int] = field(default_factory=dict)
    # True when the query exceeds MAX_BULK_ITEMS and counting stopped.
    truncated: bool = False


def parse_scrape_item(raw: dict) -> ScrapeItem:
    formats = raw.get("format") or []
    if isinstance(formats, str):
        formats = [formats]
    return ScrapeItem(
        identifier=str(raw.get("identifier", "")),
        item_size=int(raw.get("item_size") or 0),
        access_restricted=_as_bool(raw.get("access-restricted-item")),
        formats=[str(f) for f in formats],
    )


class ScrapeClient:
    """Blocking scrape client. Call from a worker thread, never the UI loop."""

    def __init__(self, session):
        self.session = session

    def pages(self, query: str, fields: str = SURVEY_FIELDS,
              cancel_event: threading.Event | None = None):
        """Yield lists of ScrapeItem, one per scrape page, to exhaustion.

        If ``cancel_event`` becomes set, stops before issuing the next
        page request (an in-flight request already sent still completes
        and is yielded — there is no way to abort it mid-flight, but no
        further requests follow).
        """
        cursor = None
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return
            params = [("q", query), ("fields", fields)]
            if cursor:
                params.append(("cursor", cursor))
            response = self.session.get(
                f"{SCRAPE_URL}?{urlencode(params)}", timeout=60
            )
            response.raise_for_status()
            payload = response.json()
            yield [parse_scrape_item(raw) for raw in payload.get("items", [])]
            cursor = payload.get("cursor")
            if not cursor:
                return

    def survey(self, query: str, max_items: int = MAX_BULK_ITEMS,
               cancel_event: threading.Event | None = None) -> Survey:
        """Measure a query: item count, total bytes, restricted count.

        Stops (with truncated=True) once max_items is exceeded so an
        overly broad query costs a handful of requests, not hundreds.
        Stops early (with a partial, non-truncated result) if
        cancel_event becomes set — e.g. the caller lost interest.
        """
        result = Survey()
        for page in self.pages(query, cancel_event=cancel_event):
            for item in page:
                result.items += 1
                result.total_bytes += item.item_size
                if item.access_restricted:
                    result.restricted += 1
                for fmt in item.formats:
                    result.formats[fmt] = result.formats.get(fmt, 0) + 1
            if result.items > max_items:
                result.truncated = True
                return result
        return result
