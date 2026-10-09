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

    def test_schedule_modification(self):
        self.cm.config["schedule"]["enabled"] = False
        self.cm.config["schedule"]["start_time"] = "10:00"
        self.cm.config["schedule"]["end_time"] = "19:00"
        self.cm.config["schedule"]["days"] = [0, 2, 4]
        self.cm.save()

        cm2 = ConfigManager(self.config_path)
        self.assertFalse(cm2.config["schedule"]["enabled"])
        self.assertEqual(cm2.config["schedule"]["start_time"], "10:00")
        self.assertEqual(cm2.config["schedule"]["end_time"], "19:00")
        self.assertEqual(cm2.config["schedule"]["days"], [0, 2, 4])

    def test_blocked_sites_add_and_remove(self):
        sites = self.cm.config["blocked_sites"]
        # Add site
        new_site = "reddit.com"
        if new_site not in sites:
            sites.append(new_site)
        self.cm.save()

        cm2 = ConfigManager(self.config_path)
        self.assertIn("reddit.com", cm2.config["blocked_sites"])

        # Remove site
        cm2.config["blocked_sites"].remove("reddit.com")
        cm2.save()

        cm3 = ConfigManager(self.config_path)
        self.assertNotIn("reddit.com", cm3.config["blocked_sites"])

    def test_timer_configuration(self):
        self.cm.config["timer"]["enabled"] = True
        self.cm.config["timer"]["daily_limit_minutes"] = 45
        self.cm.config["timer"]["spent_seconds_today"] = 120
        self.cm.save()

        cm2 = ConfigManager(self.config_path)
        self.assertTrue(cm2.config["timer"]["enabled"])
        self.assertEqual(cm2.config["timer"]["daily_limit_minutes"], 45)
        self.assertEqual(cm2.config["timer"]["spent_seconds_today"], 120)

    def test_ipc_show_signal(self):
        import socket
        import threading
        test_port = 18991
        received = []

        def dummy_server():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", test_port))
            s.listen(1)
            conn, _ = s.accept()
            msg = conn.recv(1024)
            received.append(msg)
            conn.sendall(b"OK\n")
            conn.close()
            s.close()

        t = threading.Thread(target=dummy_server)
        t.start()

        import time
        time.sleep(0.1)

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", test_port))
        client.sendall(b"SHOW\n")
        resp = client.recv(1024)
        client.close()
        t.join()

        self.assertIn(b"SHOW", received[0])
        self.assertIn(b"OK", resp)

    def test_boot_protection_config(self):
        self.assertTrue(self.cm.config["settings"]["boot_protection"])
        self.cm.config["settings"]["boot_protection"] = False
        self.cm.save()

        cm2 = ConfigManager(self.config_path)
        self.assertFalse(cm2.config["settings"]["boot_protection"])

    def test_autostart_command_format(self):
        cmd = self.cm.get_autostart_command()
        self.assertTrue(cmd.startswith('"'))
        self.assertTrue(cmd.endswith('"'))
        self.assertIn("focus_guard.pyw", cmd)
        self.assertFalse(cmd.startswith('""'))

    def test_hosts_block_verification(self):
        from blocker import Blocker, BLOCK_START_MARKER, BLOCK_END_MARKER
        b = Blocker()
        # Test string parsing with temporary hosts content
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
            tf.write("127.0.0.1 localhost\n")
            temp_path = tf.name
        
        try:
            # Point HOSTS_PATH to temp_path for testing
            import blocker
            orig_path = blocker.HOSTS_PATH
            blocker.HOSTS_PATH = temp_path
            
            self.assertFalse(b.is_hosts_blocked())
            
            # Apply block
            b.apply_hosts_block(["x.com"])
            self.assertTrue(b.is_hosts_blocked())
            self.assertTrue(b.is_hosts_blocked(["x.com"]))
            
            # Remove block
            b.remove_hosts_block()
            self.assertFalse(b.is_hosts_blocked())
            
            blocker.HOSTS_PATH = orig_path
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_version(self):
        from version import __version__
        self.assertEqual(__version__, "1.2.0")

if __name__ == "__main__":
    unittest.main()
