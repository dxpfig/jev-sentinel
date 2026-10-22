from __future__ import annotations

import sys
import unittest

from jev_sentinel.config import CommandProbe
from jev_sentinel.scanner import command_healthy


class CommandProbeTests(unittest.TestCase):
    def test_exit_zero_is_healthy(self) -> None:
        self.assertTrue(command_healthy(CommandProbe(name="ok", argv=[sys.executable, "-c", "pass"])))

    def test_exit_nonzero_is_unhealthy(self) -> None:
        self.assertFalse(
            command_healthy(CommandProbe(name="bad", argv=[sys.executable, "-c", "import sys; sys.exit(3)"]))
        )

    def test_missing_command_returns_none(self) -> None:
        self.assertIsNone(command_healthy(CommandProbe(name="empty")))


if __name__ == "__main__":
    unittest.main()

