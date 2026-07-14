"""Core search tests — no network, no GTK. Run with: python -m unittest discover tests"""

import unittest

from ia_helper.core.search import (
    LANGUAGES,
    RESULT_FIELDS,
    SearchClient,
    SearchPage,
    SearchQuery,
    parse_doc,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return FakeResponse(
            {"response": {"docs": [{"identifier": "x"}], "numFound": 1}}
        )


class TestSearchQuery(unittest.TestCase):
    def test_text_only(self):
        self.assertEqual(SearchQuery(text="apollo 11").to_lucene(), "(apollo 11)")

    def test_text_and_mediatype(self):
        query = SearchQuery(text="apollo", mediatype="movies")
        self.assertEqual(query.to_lucene(), "(apollo) AND mediatype:movies")

    def test_collection(self):
        query = SearchQuery(collection="nasa")
        self.assertEqual(query.to_lucene(), "collection:nasa")

    def test_simplelist(self):
        query = SearchQuery(simplelist=("some-parent", "mylist"))
        self.assertEqual(query.to_lucene(), "simplelists__mylist:some-parent")

    def test_empty_query_rejected(self):
        with self.assertRaises(ValueError):
            SearchQuery(text="   ").to_lucene()

    def test_language_clause_appended(self):
        english = dict(LANGUAGES)["English"]
        query = SearchQuery(text="apollo", mediatype="movies", language=english)
        self.assertEqual(
            query.to_lucene(),
            f"(apollo) AND mediatype:movies AND {english}",
        )

    def test_language_alone_is_valid(self):
        english = dict(LANGUAGES)["English"]
        self.assertEqual(SearchQuery(language=english).to_lucene(), english)

    def test_languages_table_sane(self):
        labels = [label for label, _ in LANGUAGES]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertIsNone(LANGUAGES[0][1])  # "Any language" default
        for label, clause in LANGUAGES[1:]:
            self.assertTrue(clause.startswith("language:("), label)
            self.assertTrue(clause.endswith(")"), label)
            self.assertEqual(clause.count("("), clause.count(")"), label)
            self.assertIn(" OR ", clause, label)


class TestParseDoc(unittest.TestCase):
    def test_full_doc(self):
        doc = {
            "identifier": "apollo11-video",
            "title": "Apollo 11 Video",
            "creator": ["NASA", "Someone Else"],
            "date": "1969-07-20T00:00:00Z",
            "mediatype": "movies",
            "item_size": 1234567,
            "downloads": 42,
        }
        result = parse_doc(doc)
        self.assertEqual(result.identifier, "apollo11-video")
        self.assertEqual(result.title, "Apollo 11 Video")
        self.assertEqual(result.creator, "NASA, Someone Else")
        self.assertEqual(result.date, "1969-07-20")
        self.assertEqual(result.item_size, 1234567)
        self.assertFalse(result.is_collection)

    def test_sparse_doc_falls_back_to_identifier(self):
        result = parse_doc({"identifier": "mystery-item"})
        self.assertEqual(result.title, "mystery-item")
        self.assertEqual(result.creator, "")
        self.assertEqual(result.item_size, 0)

    def test_collection_flag(self):
        result = parse_doc({"identifier": "nasa", "mediatype": "collection"})
        self.assertTrue(result.is_collection)

    def test_access_restricted_flag(self):
        # The field arrives as the string "true" (observed live) — and must
        # default to False when absent.
        result = parse_doc({"identifier": "x", "access-restricted-item": "true"})
        self.assertTrue(result.access_restricted)
        self.assertFalse(parse_doc({"identifier": "x"}).access_restricted)


class TestSearchClient(unittest.TestCase):
    def test_request_params(self):
        session = FakeSession()
        client = SearchClient(session, rows=50)
        page = client.search(SearchQuery(text="apollo"), page=2)
        params = session.calls[0]["params"]
        self.assertEqual(params["q"], "(apollo)")
        self.assertEqual(params["page"], 2)
        self.assertEqual(params["rows"], 50)
        self.assertEqual(params["fl[]"], RESULT_FIELDS)
        self.assertNotIn("sort[]", params)
        self.assertEqual(page.total, 1)
        self.assertEqual(page.results[0].identifier, "x")

    def test_sort_param(self):
        session = FakeSession()
        client = SearchClient(session)
        client.search(SearchQuery(text="apollo"), sort="downloads desc")
        self.assertEqual(session.calls[0]["params"]["sort[]"], "downloads desc")


class TestSearchPage(unittest.TestCase):
    def test_has_more(self):
        self.assertTrue(SearchPage(total=120, page=1, rows=50).has_more)
        self.assertTrue(SearchPage(total=120, page=2, rows=50).has_more)
        self.assertFalse(SearchPage(total=120, page=3, rows=50).has_more)
        self.assertFalse(SearchPage(total=0, page=1, rows=50).has_more)


if __name__ == "__main__":
    unittest.main()
