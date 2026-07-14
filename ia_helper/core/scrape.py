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

from dataclasses import dataclass
from urllib.parse import urlencode

SCRAPE_URL = "https://archive.org/services/search/v1/scrape"
SURVEY_FIELDS = "identifier,item_size,access-restricted-item"

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


@dataclass
class Survey:
    """What a bulk download would cover, measured before any confirmation."""

    items: int = 0
    total_bytes: int = 0
    restricted: int = 0
    # True when the query exceeds MAX_BULK_ITEMS and counting stopped.
    truncated: bool = False


def parse_scrape_item(raw: dict) -> ScrapeItem:
    return ScrapeItem(
        identifier=str(raw.get("identifier", "")),
        item_size=int(raw.get("item_size") or 0),
        access_restricted=_as_bool(raw.get("access-restricted-item")),
    )


class ScrapeClient:
    """Blocking scrape client. Call from a worker thread, never the UI loop."""

    def __init__(self, session):
        self.session = session

    def pages(self, query: str, fields: str = SURVEY_FIELDS):
        """Yield lists of ScrapeItem, one per scrape page, to exhaustion."""
        cursor = None
        while True:
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

    def survey(self, query: str, max_items: int = MAX_BULK_ITEMS) -> Survey:
        """Measure a query: item count, total bytes, restricted count.

        Stops (with truncated=True) once max_items is exceeded so an
        overly broad query costs a handful of requests, not hundreds.
        """
        result = Survey()
        for page in self.pages(query):
            for item in page:
                result.items += 1
                result.total_bytes += item.item_size
                if item.access_restricted:
                    result.restricted += 1
            if result.items > max_items:
                result.truncated = True
                return result
        return result
