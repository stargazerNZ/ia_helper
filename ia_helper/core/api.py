"""Shared archive.org HTTP session.

One session for the whole app so connection pooling, the User-Agent, and
(later) account credentials are configured in a single place. The IA
"Bots and Automated Access" guidelines ask automated clients to identify
themselves with a descriptive User-Agent and to keep concurrency modest;
both policies are enforced here rather than per-feature.
"""

from internetarchive import get_session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .. import PROJECT_URL, __version__

USER_AGENT = f"IAHelper/{__version__} (+{PROJECT_URL})"

# Rough budget of concurrent connections to archive.org: one search or
# metadata request, two thumbnail fetches, and up to
# config.max_concurrent_downloads (default 3, hard cap 5) downloads.
MAX_CONNECTIONS = 4


def create_session():
    """Return a configured ArchiveSession (a requests.Session subclass).

    Retries with exponential backoff on 429/5xx (honoring Retry-After, per
    IA's automated-access guidelines) are mounted for all GETs. For
    streaming downloads the retry only covers up to the response headers;
    mid-stream failures surface to the download manager, which resumes
    with a Range request instead.

    Later milestones point this at the user's ``ia`` config so stored
    S3-style credentials are picked up automatically.
    """
    session = get_session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=MAX_CONNECTIONS * 2)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
