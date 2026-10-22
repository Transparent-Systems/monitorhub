"""Unit tests for the secret-masking helpers (``app.utils.profile_display``)."""

import unittest

from app.utils import profile_display


class TestIsSecretKey(unittest.TestCase):
    """The key heuristic must catch secrets and leave identifiers alone."""

    def test_secret_keys_are_detected(self):
        for key in (
            "secret",
            "access_key_secret",
            "secret_access_key",
            "client_secret",
            "pass",
            "password",
            "passwd",
            "token",
            "bearer_token",
            "key_pem",
            "s3_sse_customer_key",
            "service_account_credentials",
        ):
            with self.subTest(key=key):
                self.assertTrue(profile_display.is_secret_key(key))

    def test_identifiers_and_settings_are_not_secret(self):
        for key in (
            "access_key_id",
            "client_id",
            "provider",
            "endpoint",
            "region",
            "scope",
            "team_drive",
            "remote_handler",
            "rclone_options",
            "transfers",
            "s3_chunk_size",
            "",
        ):
            with self.subTest(key=key):
                self.assertFalse(profile_display.is_secret_key(key))

    def test_matching_is_case_insensitive(self):
        self.assertTrue(profile_display.is_secret_key("Client_Secret"))


class TestMaskedValue(unittest.TestCase):
    def test_secret_value_is_masked(self):
        self.assertEqual(
            profile_display.masked_value("client_secret", "GOCSPX-abc"),
            profile_display.MASK,
        )

    def test_non_secret_value_is_returned(self):
        self.assertEqual(
            profile_display.masked_value("access_key_id", "AKIA-VISIBLE"), "AKIA-VISIBLE"
        )

    def test_unset_secret_is_not_masked(self):
        self.assertIsNone(profile_display.masked_value("pass", None))
        self.assertEqual(profile_display.masked_value("pass", ""), "")


class TestFormatValue(unittest.TestCase):
    def test_secret_mapping_is_masked_as_a_whole(self):
        token = {"access_token": "a", "refresh_token": "r"}
        self.assertEqual(
            profile_display.format_value("token", token), profile_display.MASK
        )

    def test_option_mapping_masks_secret_options(self):
        rendered = profile_display.format_value(
            "rclone_options",
            {"transfers": 8, "s3_sse_customer_key": "topsecret"},
        )
        self.assertIn("transfers=8", rendered)
        self.assertIn(f"s3_sse_customer_key={profile_display.MASK}", rendered)
        self.assertNotIn("topsecret", rendered)

    def test_scalar_value_is_returned(self):
        self.assertEqual(profile_display.format_value("scope", "drive"), "drive")


if __name__ == "__main__":
    unittest.main()
