"""server.py launcher — LAN-visible by default, never double-starts."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import server as launcher


class TestLauncher(unittest.TestCase):
    def test_env_forces_lan_bind(self):
        env = launcher.server_env({})
        self.assertEqual(env["HOST"], "0.0.0.0")
        self.assertEqual(env["PORT"], "8080")

    def test_env_respects_port_override(self):
        env = launcher.server_env({}, port=9090)
        self.assertEqual(env["PORT"], "9090")

    def test_refuses_start_when_port_busy(self):
        with self.assertRaises(launcher.AlreadyRunning):
            launcher.start(port_check=lambda p: True,
                           spawn=lambda *a, **k: self.fail("must not spawn"))

    def test_lan_url_composition(self):
        self.assertEqual(launcher.lan_url("192.168.0.2", 8080),
                         "http://192.168.0.2:8080")


if __name__ == "__main__":
    unittest.main()
