"""Shared archive.org HTTP session.

One session for the whole app so connection pooling, the User-Agent, and
(later) account credentials are configured in a single place. The IA
"Bots and Automated Access" guidelines ask automated clients to identify
themselves with a descriptive User-Agent and to keep concurrency modest;
both policies are enforced here rather than per-feature.
"""

from internetarchive import get_session

from .. import PROJECT_URL, __version__

USER_AGENT = f"IAHelper/{__version__} (+{PROJECT_URL})"

# Total concurrent connections the app should hold to archive.org.
# Search uses one; the thumbnail loader takes the rest.
MAX_CONNECTIONS = 4


def create_session():
    """Return a configured ArchiveSession (a requests.Session subclass).

    Later milestones point this at the user's ``ia`` config so stored
    S3-style credentials are picked up automatically.
    """
    session = get_session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session
