"""Credential storage regression checks runnable without a Django server."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from community_base.device_login import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.target = Path(self.directory.name) / "credentials.json"

    def test_round_trip_and_replace(self):
        storage.save_private_json(self.target, {"test": "first"})
        storage.save_private_json(self.target, {"test": "second"})
        self.assertEqual(storage.read_private_json(self.target), {"test": "second"})
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_failed_windows_acl_does_not_write_payload_or_replace_existing(self):
        storage.save_private_json(self.target, {"test": "original"})
        with patch.object(storage, "_windows_acl", return_value=False):
            with self.assertRaises(PermissionError):
                storage._save_windows(self.target, {"test": "replacement"})
        self.assertEqual(storage.read_private_json(self.target), {"test": "original"})
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    @unittest.skipUnless(os.name == "nt", "Windows ACL regression")
    def test_windows_read_rejects_unrestricted_acl(self):
        self.target.write_text('{"test": "fixture"}', encoding="utf-8")
        with self.assertRaises(PermissionError):
            storage.read_private_json(self.target)
        self.assertEqual(
            storage.read_private_json(self.target, enforce_mode=False), {"test": "fixture"}
        )

    def test_non_object_is_rejected(self):
        storage.save_private_json(self.target, {})
        self.target.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid"):
            storage.read_private_json(self.target)


if __name__ == "__main__":
    unittest.main()
