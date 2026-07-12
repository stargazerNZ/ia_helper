"""Core item-metadata tests — no network, no GTK."""

import unittest

from ia_helper.core.items import (
    parse_item,
    parse_simplelists,
    strip_html,
)

SAMPLE_METADATA = {
    "metadata": {
        "identifier": "apollo11-video",
        "title": "Apollo 11 Video",
        "creator": ["NASA"],
        "date": "1969-07-20T00:00:00Z",
        "description": "<p>One giant leap.</p><br>Restored &amp; remastered.",
        "mediatype": "movies",
        "collection": ["nasa", "moonlanding"],
        "subject": "Space; Moon",
    },
    "files": [
        {
            "name": "apollo11.mpg",
            "source": "original",
            "format": "MPEG2",
            "md5": "abc123",
            "size": "1073741824",
        },
        {
            "name": "apollo11.mp4",
            "source": "derivative",
            "format": "h.264",
            "md5": "def456",
            "size": "536870912",
        },
        {
            "name": "apollo11-video_meta.xml",
            "source": "metadata",
            "format": "Metadata",
            "md5": "789fff",
            "size": "1500",
        },
    ],
    "files_count": 3,
    "item_size": 1610614336,
}

# Verbatim example from https://archive.org/developers/simplelists.html:
# nesting is {list-name: {parent: {...}}}.
SAMPLE_SIMPLELISTS = {
    "result": {
        "holdings": {
            "library_of_atlantis": {
                "notes": {"isbn": "9781453262825"},
                "sys_changed_by": {"source": "task", "task_id": "718194457"},
                "sys_last_changed": "2017-08-09 01:27:03.751945",
            }
        }
    }
}


class TestParseItem(unittest.TestCase):
    def test_full_record(self):
        details = parse_item(SAMPLE_METADATA)
        self.assertEqual(details.identifier, "apollo11-video")
        self.assertEqual(details.title, "Apollo 11 Video")
        self.assertEqual(details.creator, "NASA")
        self.assertEqual(details.date, "1969-07-20")
        self.assertEqual(details.collections, ["nasa", "moonlanding"])
        self.assertEqual(details.subjects, ["Space", "Moon"])
        self.assertEqual(details.item_size, 1610614336)
        self.assertFalse(details.is_dark)
        self.assertFalse(details.is_collection)

    def test_description_html_stripped(self):
        details = parse_item(SAMPLE_METADATA)
        # </p> and <br> each contribute a break → paragraph gap.
        self.assertEqual(details.description, "One giant leap.\n\nRestored & remastered.")

    def test_files(self):
        files = parse_item(SAMPLE_METADATA).files
        self.assertEqual(len(files), 3)
        self.assertTrue(files[0].is_original)
        self.assertEqual(files[0].size, 1073741824)
        self.assertFalse(files[1].is_original)
        self.assertEqual(files[2].source, "metadata")

    def test_empty_record_rejected(self):
        with self.assertRaises(ValueError):
            parse_item({})

    def test_dark_item(self):
        payload = {"metadata": {"identifier": "dark-item"}, "is_dark": True}
        self.assertTrue(parse_item(payload).is_dark)

    def test_access_restricted_item(self):
        # Flag arrives as the string "true" in item metadata (observed live
        # on lending-library books, e.g. collection:inlibrary).
        payload = {
            "metadata": {"identifier": "book", "access-restricted-item": "true"}
        }
        self.assertTrue(parse_item(payload).access_restricted)
        self.assertFalse(parse_item({"metadata": {"identifier": "x"}}).access_restricted)

    def test_nodownload_counts_as_restricted(self):
        payload = {"metadata": {"identifier": "x"}, "nodownload": True}
        self.assertTrue(parse_item(payload).access_restricted)

    def test_private_files(self):
        payload = {
            "metadata": {"identifier": "book"},
            "files": [
                {"name": "book.pdf", "source": "derivative", "private": "true"},
                {"name": "__ia_thumb.jpg", "source": "original"},
            ],
        }
        files = parse_item(payload).files
        self.assertTrue(files[0].private)
        self.assertFalse(files[1].private)


class TestParseSimplelists(unittest.TestCase):
    def test_docs_example(self):
        memberships = parse_simplelists(SAMPLE_SIMPLELISTS)
        self.assertEqual(len(memberships), 1)
        m = memberships[0]
        self.assertEqual(m.parent, "library_of_atlantis")
        self.assertEqual(m.list_name, "holdings")
        self.assertEqual(m.to_query(), "simplelists__holdings:library_of_atlantis")

    def test_empty(self):
        self.assertEqual(parse_simplelists({"result": {}}), [])
        self.assertEqual(parse_simplelists({}), [])


class TestStripHtml(unittest.TestCase):
    def test_plain_text_untouched(self):
        self.assertEqual(strip_html("hello world"), "hello world")

    def test_tags_and_entities(self):
        self.assertEqual(
            strip_html("<b>bold</b> &amp; <i>italic</i>"), "bold & italic"
        )

    def test_breaks_become_newlines(self):
        self.assertEqual(strip_html("one<br/>two<br />three"), "one\ntwo\nthree")

    def test_excess_blank_lines_collapsed(self):
        self.assertEqual(strip_html("<p>a</p><p>b</p>"), "a\nb")


if __name__ == "__main__":
    unittest.main()
