"""告警通道：控制台预览、飞书 interactive 卡片、通用 webhook。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

logger = logging.getLogger("jev_sentinel.notifier")


class DeliveryError(Exception):
    """已明确失败；仅 retryable 为真时允许重试。"""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class DeliveryUnknown(Exception):
    """请求结果不确定，自动重试可能重复提醒。"""


class Notifier(Protocol):
    def send_card(self, card: Mapping[str, Any]) -> str: ...


class ConsoleNotifier:
    """默认安全预览，只写日志，不发任何真实通知。"""

    def send_card(self, card: Mapping[str, Any]) -> str:
        title = card.get("header", {}).get("title", {}).get("content", "告警")
        body = ""
        elements = card.get("elements", [])
        if elements:
            body = elements[0].get("text", {}).get("content", json.dumps(card, ensure_ascii=False))
        logger.info("【预览】%s\n%s", title, body)
        return "accepted"


class WebhookNotifier:
    """把卡片作为 JSON POST 到任意 HTTP 地址，可自定义请求头。"""

    def __init__(self, url: str, timeout: float = 5.0, headers: Mapping[str, str] | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self.headers = dict(headers or {})

    def send_card(self, card: Mapping[str, Any]) -> str:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(dict(card), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception:
            raise DeliveryUnknown("webhook 网络请求结果不确定") from None
        if not 200 <= status < 300:
            raise DeliveryError(f"webhook HTTP 请求被拒绝（状态 {status}）", retryable=status >= 500)
        return "accepted"


class FeishuNotifier:
    """飞书自定义机器人；接口接受不等于用户已阅读，超时结果不确定。"""

    def __init__(self, webhook: str, secret: str = "", timeout: float = 5.0) -> None:
        parsed = urlsplit(webhook)
        try:
            valid_port = parsed.port in (None, 443)
        except ValueError:
            valid_port = False
        if (
            parsed.scheme != "https"
            or parsed.hostname != "open.feishu.cn"
            or parsed.username
            or parsed.password
            or not valid_port
            or parsed.fragment
            or not parsed.path.startswith("/open-apis/bot/v2/hook/")
        ):
            raise ValueError("飞书 webhook 必须为 open.feishu.cn 的 HTTPS 自定义机器人地址")
        if timeout <= 0:
            raise ValueError("发送超时必须大于零")
        self._webhook = webhook
        self._secret = secret
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> str:
        if self._secret:
            stamp = str(int(time.time()))
            key = f"{stamp}\n{self._secret}".encode("utf-8")
            payload.update(
                timestamp=stamp,
                sign=base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode("ascii"),
            )
        request = urllib.request.Request(
            self._webhook,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            raw = error.read()
        except Exception:
            raise DeliveryUnknown("飞书网络请求结果不确定，请人工核查") from None
        if not 200 <= status < 300:
            raise DeliveryError(f"飞书 HTTP 请求被拒绝（状态 {status}）", retryable=status == 429 or status >= 500)
        try:
            body = json.loads(raw.decode("utf-8"))
            codes = [body[name] for name in ("code", "StatusCode") if name in body]
        except Exception:
            raise DeliveryUnknown("飞书响应无法确认发送结果") from None
        if not codes:
            raise DeliveryUnknown("飞书响应未包含发送状态")
        if any(code not in (0, "0") for code in codes):
            raise DeliveryError("飞书机器人业务请求被拒绝，请检查配置", retryable=False)
        return "accepted"

    def send_card(self, card: Mapping[str, Any]) -> str:
        return self._post({"msg_type": "interactive", "card": dict(card)})


def build_notifier(cfg: Any) -> Notifier:
    """根据配置构建告警通道；缺 webhook 时安全降级为控制台预览。"""
    kind = cfg.type
    if kind == "console" or not cfg.webhook:
        return ConsoleNotifier()
    if kind == "feishu":
        return FeishuNotifier(cfg.webhook, cfg.secret, cfg.timeout)
    if kind == "webhook":
        return WebhookNotifier(cfg.webhook, cfg.timeout, cfg.headers)
    raise ValueError(f"未知 notifier.type: {kind}")

