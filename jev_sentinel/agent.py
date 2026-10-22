"""哨兵主循环：扫描 → 第一层判断 → 签名去重/冷却/恢复状态机 → LLM 诊断 → 告警。"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .classify import AnomalyClassifier
from .config import AgentConfig, HealthConfig, LogSourceConfig
from .notifier import Notifier
from .scanner import LogSource, command_healthy, process_running, tcp_alive
from .signature import normalize_signature

logger = logging.getLogger("jev_sentinel.agent")


class Sentinel:
    """扫描日志与健康状态，交给模型诊断后按签名去重/冷却，异常与恢复经通知器告警。"""

    def __init__(
        self,
        agent: AgentConfig,
        logs: list[LogSourceConfig],
        health: HealthConfig,
        classifier: AnomalyClassifier,
        diagnoser: Callable[[str], dict[str, Any] | None],
        notifier: Notifier,
    ) -> None:
        self.agent = agent
        self.health = health
        self.classifier = classifier
        self.diagnoser = diagnoser
        self.notifier = notifier
        self.log_sources = [
            LogSource(item.path, item.tail_bytes, item.max_lines) for item in logs
        ]
        self.state: dict[str, dict[str, Any]] = {}
        self.context: dict[str, deque[str]] = {}
        self.log_baselined = False

    def _remember(self, signature: str, line: str) -> None:
        self.context.setdefault(signature, deque(maxlen=10)).append(line)

    def _snippet(self, signature: str) -> str:
        return "\n".join(self.context.get(signature, [signature]))

    def _send(self, title: str, signature: str, diagnosis: dict[str, Any] | None = None) -> None:
        tz = timezone(timedelta(hours=self.agent.timezone_hours))
        now_text = datetime.fromtimestamp(time.time(), tz).strftime("%Y-%m-%d %H:%M:%S")
        if diagnosis:
            lines = [f"**问题**：{diagnosis.get('summary', '')}"]
            if diagnosis.get("cause"):
                lines.append(f"**可能原因**：{diagnosis['cause']}")
            if diagnosis.get("suggestion"):
                lines.append(f"**处理建议**：{diagnosis['suggestion']}")
            lines.append(f"**严重程度**：{diagnosis.get('severity', 'unknown')}")
            lines.append("")
            lines.append(f"日志签名：{signature}")
            lines.append(f"时间：{now_text}")
            body = "\n".join(lines)
        else:
            body = signature + "\n时间：" + now_text
        template = "red" if ("出现" in title or "持续" in title) else "green"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": body}}],
        }
        try:
            self.notifier.send_card(card)
        except Exception:
            logger.exception("告警发送失败")
        else:
            logger.info("已发送告警：%s | %s", title, signature)

    def _observe(self, signature: str, present: bool, notify_first: bool) -> None:
        entry = self.state.setdefault(
            signature,
            {
                "active": False,
                "last_seen": 0.0,
                "last_notified": 0.0,
                "absent": 0,
                "diagnosis": None,
            },
        )
        now = time.time()
        if present:
            entry["last_seen"] = now
            entry["absent"] = 0
            if not entry["active"]:
                entry["active"] = True
                if notify_first:
                    entry["diagnosis"] = self.diagnoser(self._snippet(signature))
                    self._send("运维告警 · 出现", signature, entry["diagnosis"])
                entry["last_notified"] = now
            elif now - entry["last_notified"] >= self.agent.cooldown_seconds:
                if entry["diagnosis"] is None and signature in self.context:
                    entry["diagnosis"] = self.diagnoser(self._snippet(signature))
                self._send("运维告警 · 仍持续", signature, entry["diagnosis"])
                entry["last_notified"] = now
        elif entry["active"]:
            entry["absent"] += 1
            if entry["absent"] >= self.agent.grace_scans:
                entry["active"] = False
                entry["absent"] = 0
                self._send("运维告警 · 已恢复", signature)

    def _prune(self) -> None:
        now = time.time()
        stale = [
            key for key, value in self.state.items()
            if now - value["last_seen"] > self.agent.horizon_seconds
        ]
        for key in stale:
            self.state.pop(key, None)

    def scan_once(self) -> None:
        judged = 0
        for source in self.log_sources:
            if judged >= self.agent.max_lines_per_scan:
                break
            for line in source.lines_to_scan():
                if judged >= self.agent.max_lines_per_scan:
                    break
                judged += 1
                is_anomaly, _probability, _source = self.classifier.is_anomaly(line)
                if not is_anomaly:
                    continue
                signature = normalize_signature(line)
                if signature:
                    self._remember(signature, line)
                    self._observe(signature, True, notify_first=self.log_baselined)
        self.log_baselined = True

        for name in self.health.processes:
            running = process_running(name)
            if running is not None:
                self._observe(f"健康检查：进程未运行（{name}）", not running, notify_first=True)
        for endpoint in self.health.tcp:
            self._observe(
                f"健康检查：端口不可达（{endpoint}）", not tcp_alive(endpoint), notify_first=True
            )
        for probe in self.health.commands:
            healthy = command_healthy(probe)
            if healthy is not None:
                self._observe(f"健康检查：{probe.name}", not healthy, notify_first=True)
        self._prune()

    def run_forever(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception:
                logger.exception("运维扫描失败")
            time.sleep(self.agent.interval_seconds)

