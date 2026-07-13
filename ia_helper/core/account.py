"""Internet Archive account integration.

Sign-in delegates to ``internetarchive.configure()``, which exchanges the
email/password for S3-style API keys and writes them to the standard ``ia``
config file — the password itself is used once and never stored.
``get_session()`` (see api.py) picks the keys up automatically, so the
whole app becomes authenticated after the session is recreated.

Who-am-I uses the S3 check_auth endpoint (the same call the
internetarchive library uses), which maps the keys to the account email,
screen name, and @itemname — the itemname is what the favorites
pseudo-collection (``fav-<itemname>``) is keyed on, NOT the email.

The internetarchive import is deferred into login() so this module stays
importable (and testable) without the library installed.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

CHECK_AUTH_URL = "https://s3.us.archive.org"


@dataclass
class AccountInfo:
    email: str
    itemname: str = ""    # "@screenname" — keys the fav-* pseudo-collection
    screenname: str = ""

    @property
    def favorites_query(self) -> str:
        if not self.itemname:
            return ""
        return f"collection:fav-{self.itemname.lstrip('@')}"

    @property
    def uploads_query(self) -> str:
        return f'uploader:"{self.email}"'

    @property
    def display_name(self) -> str:
        return self.screenname or self.itemname or self.email


def config_file_candidates() -> list[Path]:
    """Locations the ia tool writes/reads its config, in search order."""
    candidates = []
    env = os.environ.get("IA_CONFIG_FILE")
    if env:
        candidates.append(Path(env))
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    candidates.append(base / "internetarchive" / "ia.ini")
    candidates.append(base / "ia.ini")
    candidates.append(Path.home() / ".ia")
    return candidates


def find_config_file() -> Path | None:
    for path in config_file_candidates():
        if path.is_file():
            return path
    return None


def login(email: str, password: str) -> None:
    """Exchange credentials for S3 keys, written to the ia config file.

    Raises internetarchive's AuthenticationError on bad credentials.
    Blocking (network) — call from a worker thread.
    """
    from internetarchive import configure

    configure(email, password)


def logout() -> bool:
    """Remove stored credentials (the [s3] and [cookies] config sections).

    Returns True if anything was removed. Other sections (e.g. [general])
    are preserved.
    """
    path = find_config_file()
    if path is None:
        return False
    parser = configparser.RawConfigParser()
    parser.read(path)
    removed = False
    for section in ("s3", "cookies"):
        removed = parser.remove_section(section) or removed
    if removed:
        with path.open("w") as handle:
            parser.write(handle)
    return removed


def parse_user_info(payload: dict) -> AccountInfo:
    return AccountInfo(
        email=unquote(str(payload.get("username") or "")),
        itemname=str(payload.get("itemname") or ""),
        screenname=str(payload.get("screenname") or ""),
    )


def fetch_user_info(session) -> AccountInfo | None:
    """Resolve the session's stored keys to an account, or None.

    No network when the session has no keys. Blocking otherwise — call
    from a worker thread.
    """
    access = getattr(session, "access_key", None)
    secret = getattr(session, "secret_key", None)
    if not access or not secret:
        return None
    response = session.get(
        CHECK_AUTH_URL,
        params={"check_auth": 1},
        headers={"Authorization": f"LOW {access}:{secret}"},
        timeout=15,
    )
    if not response.ok:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    info = parse_user_info(payload)
    return info if info.email else None
