"""Tests for app_version / VERSION file."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch


class AppVersionTest(unittest.TestCase):
    def test_reads_version_file(self):
        import app_version

        app_version.get_version.cache_clear()
        ver = app_version.get_version()
        self.assertRegex(ver, r"^\d+\.\d+\.\d+")
        self.assertEqual(app_version.get_version_display(), f"v{ver}")
        major, minor, patch = app_version.parse_semver(ver)
        self.assertGreaterEqual(major, 0)

    def test_env_override(self):
        import app_version

        app_version.get_version.cache_clear()
        with patch.dict(os.environ, {"APP_VERSION": "9.8.7"}, clear=False):
            app_version.get_version.cache_clear()
            self.assertEqual(app_version.get_version(), "9.8.7")
            self.assertEqual(app_version.get_version_display(), "v9.8.7")
        app_version.get_version.cache_clear()

    def test_version_file_exists(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "VERSION").is_file())


if __name__ == "__main__":
    unittest.main()
