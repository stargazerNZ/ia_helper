"""Account tests — no network, no internetarchive import required."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ia_helper.core.account import (
    AccountInfo,
    config_file_candidates,
    find_config_file,
    fetch_user_info,
    logout,
    parse_user_info,
)


class TestAccountInfo(unittest.TestCase):
    def test_queries(self):
        info = AccountInfo(
            email="joe@example.com", itemname="@joetest", screenname="Joe"
        )
        self.assertEqual(info.favorites_query, "collection:fav-joetest")
        self.assertEqual(info.uploads_query, 'uploader:"joe@example.com"')
        self.assertEqual(info.display_name, "Joe")

    def test_no_itemname_means_no_favorites_query(self):
        info = AccountInfo(email="joe@example.com")
        self.assertEqual(info.favorites_query, "")
        self.assertEqual(info.display_name, "joe@example.com")


class TestParseUserInfo(unittest.TestCase):
    def test_parses_and_unquotes(self):
        # check_auth returns the username URL-encoded.
        payload = {
            "username": "joe%40example.com",
            "itemname": "@joetest",
            "screenname": "Joe",
        }
        info = parse_user_info(payload)
        self.assertEqual(info.email, "joe@example.com")
        self.assertEqual(info.itemname, "@joetest")

    def test_missing_fields(self):
        info = parse_user_info({})
        self.assertEqual(info.email, "")


class TestFetchUserInfo(unittest.TestCase):
    def test_no_keys_no_network(self):
        session = mock.Mock(spec=[])  # no access_key attr, .get would explode
        self.assertIsNone(fetch_user_info(session))

    def test_with_keys_calls_check_auth(self):
        session = mock.Mock()
        session.access_key = "AK"
        session.secret_key = "SK"
        session.get.return_value = mock.Mock(
            ok=True,
            json=lambda: {"username": "a%40b.com", "itemname": "@a"},
        )
        info = fetch_user_info(session)
        self.assertEqual(info.email, "a@b.com")
        headers = session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "LOW AK:SK")

    def test_error_payload_returns_none(self):
        session = mock.Mock()
        session.access_key = "AK"
        session.secret_key = "SK"
        session.get.return_value = mock.Mock(
            ok=True, json=lambda: {"error": "bad key"}
        )
        self.assertIsNone(fetch_user_info(session))


class TestConfigFile(unittest.TestCase):
    def test_env_var_takes_priority(self):
        with mock.patch.dict(os.environ, {"IA_CONFIG_FILE": "/tmp/custom.ini"}):
            self.assertEqual(config_file_candidates()[0], Path("/tmp/custom.ini"))

    def test_logout_removes_credential_sections_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ia.ini"
            path.write_text(
                "[s3]\naccess = AK\nsecret = SK\n"
                "[cookies]\nlogged-in-user = x\n"
                "[general]\nscreenname = Joe\n"
            )
            with mock.patch.dict(os.environ, {"IA_CONFIG_FILE": str(path)}):
                self.assertEqual(find_config_file(), path)
                self.assertTrue(logout())
                text = path.read_text()
            self.assertNotIn("[s3]", text)
            self.assertNotIn("[cookies]", text)
            self.assertIn("[general]", text)

    def test_logout_without_config_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.ini"
            with mock.patch.dict(os.environ, {"IA_CONFIG_FILE": str(missing)}):
                with mock.patch(
                    "ia_helper.core.account.config_file_candidates",
                    return_value=[missing],
                ):
                    self.assertFalse(logout())


if __name__ == "__main__":
    unittest.main()
