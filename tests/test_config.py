from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jev_sentinel.config import load_config


class ConfigLoadTests(unittest.TestCase):
    def test_health_commands_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.toml"
            path.write_text(
                '[health]\n[[health.commands]]\nname="采集器"\ncwd="/tmp"\nargv=["python", "-c", "pass"]\n',
                encoding="utf-8",
            )
            cfg = load_config(path)
            self.assertEqual(len(cfg.health.commands), 1)
            self.assertEqual(cfg.health.commands[0].name, "采集器")
            self.assertEqual(cfg.health.commands[0].argv, ["python", "-c", "pass"])
            self.assertEqual(cfg.health.commands[0].cwd, "/tmp")


if __name__ == "__main__":
    unittest.main()
