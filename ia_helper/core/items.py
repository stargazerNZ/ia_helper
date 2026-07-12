"""Item metadata via the Item Metadata API.

One GET to https://archive.org/metadata/<identifier> returns the whole
record: descriptive metadata, the complete file list, size, and state
flags. A second, optional GET to .../simplelists returns the item's
simple-list memberships, shaped {"result": {<list-name>: {<parent>: {...}}}}
(so the corresponding search query is ``simplelists__<list-name>:<parent>``).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

METADATA_URL = "https://archive.org/metadata/{identifier}"
SIMPLELISTS_URL = "https://archive.org/metadata/{identifier}/simplelists"

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<(?:br|/p|/div)[^>]*>", re.IGNORECASE)
_BLANK_LINES = re.compile(r"\n{3,}")


def strip_html(text: str) -> str:
    """Reduce the HTML fragments IA allows in descriptions to plain text."""
    text = _BREAK.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _as_text(value, separator: str = ", ") -> str:
    return separator.join(_as_list(value))


def _as_bool(value) -> bool:
    """IA boolean flags arrive as True, "true", or are absent entirely."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


@dataclass
class FileEntry:
    name: str
    size: int = 0
    format: str = ""
    md5: str = ""
    # archive.org marks each file "original", "derivative", or "metadata".
    source: str = ""
    # private=true files (e.g. lending-library book content) are not
    # downloadable; the download endpoint returns 403 for them.
    private: bool = False

    @property
    def is_original(self) -> bool:
        return self.source == "original"


@dataclass
class SimpleListMembership:
    parent: str
    list_name: str

    def to_query(self) -> str:
        return f"simplelists__{self.list_name}:{self.parent}"

    @property
    def label(self) -> str:
        return f"{self.parent} / {self.list_name}"


@dataclass
class ItemDetails:
    identifier: str
    title: str
    description: str = ""
    creator: str = ""
    date: str = ""
    mediatype: str = ""
    collections: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)
    item_size: int = 0
    files_count: int = 0
    is_dark: bool = False
    # Lending-library and similar items (access-restricted-item metadata
    # flag): viewable on archive.org, but their content files are private.
    access_restricted: bool = False

    @property
    def is_collection(self) -> bool:
        return self.mediatype == "collection"


def parse_file(raw: dict) -> FileEntry:
    return FileEntry(
        name=str(raw.get("name", "")),
        size=int(raw.get("size") or 0),
        format=str(raw.get("format", "")),
        md5=str(raw.get("md5", "")),
        source=str(raw.get("source", "")),
        private=_as_bool(raw.get("private")),
    )


def parse_item(payload: dict) -> ItemDetails:
    metadata = payload.get("metadata") or {}
    identifier = str(metadata.get("identifier", ""))
    if not identifier:
        raise ValueError("no such item (empty metadata record)")

    subjects: list[str] = []
    for entry in _as_list(metadata.get("subject")):
        # Subjects arrive as a list, a single string, or one ";"-joined string.
        subjects.extend(s.strip() for s in entry.split(";") if s.strip())

    description = "\n\n".join(_as_list(metadata.get("description")))
    return ItemDetails(
        identifier=identifier,
        title=_as_text(metadata.get("title")) or identifier,
        description=strip_html(description),
        creator=_as_text(metadata.get("creator")),
        date=_as_text(metadata.get("date"))[:10],
        mediatype=_as_text(metadata.get("mediatype")),
        collections=_as_list(metadata.get("collection")),
        subjects=subjects,
        files=[parse_file(f) for f in payload.get("files") or []],
        item_size=int(payload.get("item_size") or 0),
        files_count=int(payload.get("files_count") or 0),
        is_dark=_as_bool(payload.get("is_dark")),
        access_restricted=(
            _as_bool(metadata.get("access-restricted-item"))
            or _as_bool(payload.get("nodownload"))
        ),
    )


def parse_simplelists(payload: dict) -> list[SimpleListMembership]:
    memberships = []
    for list_name, parents in (payload.get("result") or {}).items():
        if isinstance(parents, dict):
            for parent in parents:
                memberships.append(
                    SimpleListMembership(parent=str(parent), list_name=str(list_name))
                )
    return sorted(memberships, key=lambda m: m.label)


class ItemClient:
    """Blocking metadata client. Call from a worker thread, never the UI loop."""

    def __init__(self, session):
        self.session = session

    def get_item(self, identifier: str) -> ItemDetails:
        url = METADATA_URL.format(identifier=identifier)
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return parse_item(response.json())

    def get_simplelists(self, identifier: str) -> list[SimpleListMembership]:
        url = SIMPLELISTS_URL.format(identifier=identifier)
        response = self.session.get(url, timeout=30)
        if not response.ok:
            return []
        try:
            return parse_simplelists(response.json())
        except ValueError:
            return []
