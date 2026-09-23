import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentContractTest(unittest.TestCase):
    def test_release_installs_and_verifies_both_timers(self):
        release = (ROOT / "deploy/release.sh").read_text()
        install = (ROOT / "deploy/install-operations.sh").read_text()
        self.assertIn("./deploy/install-operations.sh", release)
        for timer in ("deathmatch-update.timer", "deathmatch-entries.timer"):
            self.assertIn(timer, release)
            self.assertIn(timer, install)
        self.assertIn('systemctl is-enabled --quiet "$timer"', release)
        self.assertIn('systemctl is-active --quiet "$timer"', release)


if __name__ == "__main__":
    unittest.main()
