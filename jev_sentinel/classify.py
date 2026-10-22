"""第一层异常判断：本地小模型优先，正则兜底，保证模型故障不中断监控链路。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Protocol

from .signature import is_error_line, is_ignorable_line

logger = logging.getLogger("jev_sentinel.classify")

ANOMALY_INSTRUCTION = "这条运行日志表示系统发生了异常或错误。"


class AnomalyClassifier(Protocol):
    def is_anomaly(self, line: str) -> tuple[bool, float | None, str]: ...


class RegexClassifier:
    """零依赖兜底：命中错误关键词即视为异常，不调用任何模型。"""

    def is_anomaly(self, line: str) -> tuple[bool, float | None, str]:
        return is_error_line(line), None, "regex"


class JevStyleClassifier:
    """本地 Jev-Style 决策模型做「是否异常」判断，加载或推理失败时回退正则。"""

    def __init__(
        self,
        threshold: float = 0.5,
        model: str = "",
        base_url: str = "",
    ) -> None:
        self.threshold = threshold
        self.model = model
        self.base_url = base_url
        self._client: Any = None
        self._noul: Any = None
        self._failed = False

    def _load(self) -> None:
        from jev_style import JevStyle, noul  # 惰性导入，避免拖慢轻量启动

        self._noul = noul
        if self.base_url:
            self._client = JevStyle(base_url=self.base_url)
        elif self.model:
            self._client = JevStyle.from_pretrained(self.model)
        else:
            self._client = JevStyle()  # 内置默认 release：Jev-Style 0.8B Decision v3
        logger.info("Jev-Style 本地决策模型已加载")

    def is_anomaly(self, line: str) -> tuple[bool, float | None, str]:
        if is_ignorable_line(line):
            return False, None, "skip"
        if self._client is None and not self._failed:
            try:
                self._load()
            except Exception:
                self._failed = True
                logger.exception("Jev-Style 模型加载失败，回退正则判断")
        if self._client is None:
            return is_error_line(line), None, "regex"
        try:
            result = self._client.decide(
                line.strip(), {"anomaly": self._noul(ANOMALY_INSTRUCTION)}
            )
            probability = float(result["answers"]["anomaly"]["noul"])
            return probability >= self.threshold, probability, "jev"
        except Exception:
            logger.exception("Jev-Style 判断失败，回退正则判断")
            self._failed = True
            return is_error_line(line), None, "regex"


class OllamaClassifier:
    """通过 Ollama 本地服务用任意小模型做第一层判断，失败时回退正则。"""

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        threshold: float = 0.5,
        timeout: float = 60.0,
    ) -> None:
        if not model:
            raise ValueError("ollama 分类器必须配置 classifier.model")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.threshold = threshold
        self.timeout = timeout
        self._failed = False

    def _ask(self, line: str) -> float:
        from .llm import extract_json_object

        prompt = (
            "判断下面这行运行日志是否表示系统发生异常或错误。"
            "只输出一个 JSON 对象，形如 {\"anomaly\": 0.0}，0.0 表示正常，1.0 表示异常。\n\n"
            f"日志：{line}"
        )
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = str(body["message"]["content"])
        obj = extract_json_object(content)
        if isinstance(obj, dict):
            for key in ("anomaly", "probability", "score"):
                if key in obj:
                    return float(obj[key])
        return float(content.strip())

    def is_anomaly(self, line: str) -> tuple[bool, float | None, str]:
        if is_ignorable_line(line):
            return False, None, "skip"
        if self._failed:
            return is_error_line(line), None, "regex"
        try:
            probability = self._ask(line)
            return probability >= self.threshold, probability, "ollama"
        except Exception:
            logger.exception("Ollama 判断失败，回退正则判断")
            self._failed = True
            return is_error_line(line), None, "regex"


def build_classifier(cfg: Any) -> AnomalyClassifier:
    """根据配置构建第一层分类器；禁用或未知类型一律回退正则。"""
    if not getattr(cfg, "enabled", True) or getattr(cfg, "type", "regex") == "regex":
        return RegexClassifier()
    kind = cfg.type
    if kind == "jev":
        return JevStyleClassifier(
            threshold=cfg.threshold, model=cfg.model, base_url=cfg.base_url,
        )
    if kind == "ollama":
        return OllamaClassifier(
            model=cfg.model, base_url=cfg.base_url or "http://127.0.0.1:11434",
            threshold=cfg.threshold,
        )
    raise ValueError(f"未知 classifier.type: {kind}")

