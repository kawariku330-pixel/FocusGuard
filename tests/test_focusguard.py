import os
import unittest
import tempfile
import json
from datetime import date
from config_manager import ConfigManager, DEFAULT_CONFIG
from blocker import normalize_domain, expand_domains

class TestFocusGuard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "test_config.json")
        self.cm = ConfigManager(self.config_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_config_load(self):
        cfg = self.cm.config
        self.assertTrue(cfg["enabled"])
        self.assertIn("x.com", cfg["blocked_sites"])
        self.assertEqual(cfg["schedule"]["start_time"], "09:00")
        self.assertEqual(cfg["schedule"]["end_time"], "18:00")

    def test_save_and_reload(self):
        self.cm.config["blocked_sites"].append("youtube.com")
        self.cm.save()

        cm2 = ConfigManager(self.config_path)
        self.assertIn("youtube.com", cm2.config["blocked_sites"])

    def test_password_hashing(self):
        self.assertFalse(self.cm.has_password())
        self.assertTrue(self.cm.check_password("anything"))  # No password set

        self.cm.set_password("secret123")
        self.assertTrue(self.cm.has_password())
        self.assertTrue(self.cm.check_password("secret123"))
        self.assertFalse(self.cm.check_password("wrong"))

        # Clear password
        self.cm.set_password("")
        self.assertFalse(self.cm.has_password())

    def test_domain_normalization(self):
        self.assertEqual(normalize_domain("https://x.com/home"), "x.com")
        self.assertEqual(normalize_domain("HTTP://TWITTER.COM:443/test"), "twitter.com")
        self.assertEqual(normalize_domain("youtube.com"), "youtube.com")
        self.assertEqual(normalize_domain("www.instagram.com/p/123"), "www.instagram.com")

    def test_domain_expansion(self):
        expanded = expand_domains(["x.com"])
        self.assertIn("x.com", expanded)
        self.assertIn("www.x.com", expanded)
        self.assertIn("twitter.com", expanded)
        self.assertIn("api.x.com", expanded)

if __name__ == "__main__":
    unittest.main()
