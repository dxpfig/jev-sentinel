from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jev_sentinel.agent import Sentinel
from jev_sentinel.classify import RegexClassifier
from jev_sentinel.config import AgentConfig, HealthConfig, LogSourceConfig


class FakeNotifier:
    def __init__(self) -> None:
        self.cards: list[dict] = []

    def send_card(self, card: dict) -> str:
        self.cards.append(card)
        return "accepted"


def _make_sentinel(notifier: FakeNotifier, diagnoser=None, logs: list[LogSourceConfig] | None = None) -> Sentinel:
    return Sentinel(
        agent=AgentConfig(interval_seconds=60, cooldown_seconds=3600, grace_scans=2),
        logs=logs or [],
        health=HealthConfig(),
        classifier=RegexClassifier(),
        diagnoser=diagnoser or (lambda snippet: None),
        notifier=notifier,
    )


class ObserveStateMachineTests(unittest.TestCase):
    def test_appear_sustain_and_recover(self) -> None:
        notifier = FakeNotifier()
        agent = _make_sentinel(notifier)
        agent._observe("签名A", True, notify_first=True)
        self.assertEqual(len(notifier.cards), 1)
        self.assertIn("出现", notifier.cards[0]["header"]["title"]["content"])

        agent._observe("签名A", True, notify_first=True)
        self.assertEqual(len(notifier.cards), 1)

        agent.state["签名A"]["last_notified"] -= 3600
        agent._observe("签名A", True, notify_first=True)
        self.assertEqual(len(notifier.cards), 2)
        self.assertIn("仍持续", notifier.cards[1]["header"]["title"]["content"])

        agent._observe("签名A", False, notify_first=True)
        agent._observe("签名A", False, notify_first=True)
        self.assertEqual(len(notifier.cards), 3)
        self.assertIn("已恢复", notifier.cards[2]["header"]["title"]["content"])

    def test_baseline_does_not_notify(self) -> None:
        notifier = FakeNotifier()
        agent = _make_sentinel(notifier)
        agent._observe("历史错误", True, notify_first=False)
        self.assertEqual(notifier.cards, [])
        self.assertTrue(agent.state["历史错误"]["active"])

    def test_diagnosis_included_in_card(self) -> None:
        notifier = FakeNotifier()
        agent = _make_sentinel(
            notifier,
            diagnoser=lambda snippet: {
                "summary": "行情接口异常",
                "cause": "行情服务掉线",
                "suggestion": "检查行情账号",
                "severity": "high",
            },
        )
        agent._remember("接口异常", "获取报表数据错误: server ruturn none")
        agent._observe("接口异常", True, notify_first=True)
        content = notifier.cards[0]["elements"][0]["text"]["content"]
        self.assertIn("行情接口异常", content)
        self.assertIn("行情服务掉线", content)
        self.assertIn("high", content)


class ScanOnceTests(unittest.TestCase):
    def test_new_error_notified_after_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "app.log"
            log_path.write_text("2026-10-20 09:00:00 数据库连接失败\n", encoding="utf-8")
            notifier = FakeNotifier()
            agent = _make_sentinel(notifier, logs=[LogSourceConfig(path=str(log_path))])

            agent.scan_once()  # 首轮基线：只建立状态，不告警
            self.assertEqual(notifier.cards, [])

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("2026-10-20 09:01:00 行情接口错误: timeout\n")
            agent.scan_once()  # 新增异常：告警
            self.assertEqual(len(notifier.cards), 1)
            self.assertIn("出现", notifier.cards[0]["header"]["title"]["content"])


if __name__ == "__main__":
    unittest.main()
