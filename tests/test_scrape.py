"""Scrape client tests — fake session, no network."""

import unittest
from urllib.parse import parse_qs, urlparse

from ia_helper.core.scrape import ScrapeClient, parse_scrape_item


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeScrapeSession:
    """Serves canned cursor pages; records every request's params."""

    def __init__(self, pages):
        self.pages = pages  # list of item-dict lists
        self.calls = []

    def get(self, url, timeout=None):
        params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.calls.append(params)
        index = int(params.get("cursor", "page0").removeprefix("page"))
        payload = {
            "items": self.pages[index],
            "count": len(self.pages[index]),
            "total": sum(len(p) for p in self.pages),
        }
        if index + 1 < len(self.pages):
            payload["cursor"] = f"page{index + 1}"
        return FakeResponse(payload)


def item(ident, size=100, restricted=False):
    raw = {"identifier": ident, "item_size": size}
    if restricted:
        raw["access-restricted-item"] = "true"
    return raw


class TestScrapeClient(unittest.TestCase):
    def test_pages_follow_cursor_to_exhaustion(self):
        session = FakeScrapeSession(
            [[item("a"), item("b")], [item("c")], [item("d")]]
        )
        client = ScrapeClient(session)
        pages = list(client.pages("collection:x"))
        self.assertEqual([len(p) for p in pages], [2, 1, 1])
        self.assertEqual(pages[2][0].identifier, "d")

    def test_count_param_never_sent(self):
        # Live-verified quirk: count=100 with a cursor silently repeats
        # page 1 forever. The client must never send count.
        session = FakeScrapeSession([[item("a")], [item("b")]])
        client = ScrapeClient(session)
        list(client.pages("collection:x"))
        for call in session.calls:
            self.assertNotIn("count", call)
        self.assertEqual(session.calls[1]["cursor"], "page1")

    def test_survey_sums_and_counts(self):
        session = FakeScrapeSession(
            [[item("a", 1000), item("b", 500, restricted=True)], [item("c", 250)]]
        )
        survey = ScrapeClient(session).survey("collection:x")
        self.assertEqual(survey.items, 3)
        self.assertEqual(survey.total_bytes, 1750)
        self.assertEqual(survey.restricted, 1)
        self.assertFalse(survey.truncated)

    def test_survey_truncates_broad_queries(self):
        session = FakeScrapeSession(
            [[item(f"i{n}") for n in range(50)], [item("more")]]
        )
        survey = ScrapeClient(session).survey("mediatype:texts", max_items=10)
        self.assertTrue(survey.truncated)
        # Stopped after the first page — no second request issued.
        self.assertEqual(len(session.calls), 1)

    def test_parse_item(self):
        parsed = parse_scrape_item(
            {"identifier": "x", "item_size": "42", "access-restricted-item": "true"}
        )
        self.assertEqual(parsed.item_size, 42)
        self.assertTrue(parsed.access_restricted)


if __name__ == "__main__":
    unittest.main()
