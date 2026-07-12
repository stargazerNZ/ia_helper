"""Search against the archive.org advanced search API.

We call ``advancedsearch.php`` directly (through the shared session) rather
than ``internetarchive.search_items()`` because the library silently switches
between the scrape API and advanced search depending on the params it is
given; for an interactive, page-at-a-time UI we want explicit control.
Advanced search caps deep pagination at ~10,000 results — fine for browsing.
The Scrape API is the tool for exhaustive result sets and belongs to the
parked "sets of items" feature.

Grouping queries supported here (see docs/groupings notes in README):
  - collections:   collection:<identifier>
  - simple lists:  simplelists__<listname>:<parent-identifier>
  - favorites:     collection:fav-<username>  (just a collection query)
"""

from __future__ import annotations

from dataclasses import dataclass, field

ADVANCED_SEARCH_URL = "https://archive.org/advancedsearch.php"

# Fields requested for result rows. Keep this list short: every extra field
# inflates the response for all 50 rows.
RESULT_FIELDS = [
    "identifier",
    "title",
    "creator",
    "date",
    "mediatype",
    "item_size",
    "downloads",
]

# (label, mediatype value) pairs for the UI filter. None = no filter.
MEDIATYPES = [
    ("All types", None),
    ("Texts", "texts"),
    ("Movies", "movies"),
    ("Audio", "audio"),
    ("Images", "image"),
    ("Software", "software"),
    ("Data", "data"),
    ("Collections", "collection"),
]


@dataclass
class SearchQuery:
    """A structured query, converted to Lucene syntax with to_lucene()."""

    text: str = ""
    mediatype: str | None = None
    collection: str | None = None
    # (parent_identifier, list_name) — members of a simple list.
    simplelist: tuple[str, str] | None = None

    def to_lucene(self) -> str:
        parts: list[str] = []
        if self.text.strip():
            parts.append(f"({self.text.strip()})")
        if self.mediatype:
            parts.append(f"mediatype:{self.mediatype}")
        if self.collection:
            parts.append(f"collection:{self.collection}")
        if self.simplelist:
            parent, list_name = self.simplelist
            parts.append(f"simplelists__{list_name}:{parent}")
        if not parts:
            raise ValueError("empty query")
        return " AND ".join(parts)


@dataclass
class SearchResult:
    identifier: str
    title: str
    creator: str = ""
    date: str = ""
    mediatype: str = ""
    item_size: int = 0
    downloads: int = 0

    @property
    def is_collection(self) -> bool:
        return self.mediatype == "collection"


@dataclass
class SearchPage:
    results: list[SearchResult] = field(default_factory=list)
    total: int = 0
    page: int = 1
    rows: int = 50

    @property
    def has_more(self) -> bool:
        return self.page * self.rows < self.total


def _as_text(value) -> str:
    """Advanced search returns some fields as either str or list of str."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def parse_doc(doc: dict) -> SearchResult:
    identifier = doc.get("identifier", "")
    return SearchResult(
        identifier=identifier,
        title=_as_text(doc.get("title")) or identifier,
        creator=_as_text(doc.get("creator")),
        date=_as_text(doc.get("date"))[:10],
        mediatype=_as_text(doc.get("mediatype")),
        item_size=int(doc.get("item_size") or 0),
        downloads=int(doc.get("downloads") or 0),
    )


class SearchClient:
    """Blocking search client. Call from a worker thread, never the UI loop."""

    def __init__(self, session, rows: int = 50):
        self.session = session
        self.rows = rows

    def search(self, query: SearchQuery, page: int = 1) -> SearchPage:
        params = {
            "q": query.to_lucene(),
            "fl[]": RESULT_FIELDS,
            "rows": self.rows,
            "page": page,
            "output": "json",
        }
        response = self.session.get(ADVANCED_SEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json().get("response", {})
        return SearchPage(
            results=[parse_doc(d) for d in payload.get("docs", [])],
            total=int(payload.get("numFound") or 0),
            page=page,
            rows=self.rows,
        )
