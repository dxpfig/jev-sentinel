from __future__ import annotations

import unittest

from jev_sentinel.notifier import ConsoleNotifier, FeishuNotifier


class FeishuNotifierTests(unittest.TestCase):
    def test_valid_webhook_accepted(self) -> None:
        notifier = FeishuNotifier("https://open.feishu.cn/open-apis/bot/v2/hook/abc123")
        self.assertEqual(notifier.timeout, 5.0)

    def test_invalid_scheme_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FeishuNotifier("http://open.feishu.cn/open-apis/bot/v2/hook/abc123")

    def test_wrong_host_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FeishuNotifier("https://example.com/open-apis/bot/v2/hook/abc123")

    def test_missing_path_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FeishuNotifier("https://open.feishu.cn/other")


class ConsoleNotifierTests(unittest.TestCase):
    def test_send_card_returns_accepted(self) -> None:
        self.assertEqual(ConsoleNotifier().send_card({}), "accepted")


if __name__ == "__main__":
    unittest.main()

