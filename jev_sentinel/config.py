"""配置加载：TOML 文件 + 环境变量覆盖。不执行任何来自配置的代码。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

ENV_PREFIX = "JEV_SENTINEL_"


@dataclass
class LogSourceConfig:
    """一个需要被扫描的日志文件（支持 glob 通配符）。"""

    path: str
    tail_bytes: int = 131072
    max_lines: int = 1000


@dataclass
class CommandProbe:
    """一个自定义健康探测命令：退出码 0 视为健康。"""

    name: str
    argv: list[str] = field(default_factory=list)
    shell: str = ""
    cwd: str = ""


@dataclass
class HealthConfig:
    """进程、TCP 端口与自定义命令健康探测。"""

    processes: list[str] = field(default_factory=list)
    tcp: list[str] = field(default_factory=list)
    commands: list[CommandProbe] = field(default_factory=list)


@dataclass
class ClassifierConfig:
    """第一层异常判断：regex / jev / ollama。"""

    type: str = "regex"
    enabled: bool = True
    threshold: float = 0.5
    model: str = ""
    base_url: str = ""


@dataclass
class LLMConfig:
    """第二层诊断用的 OpenAI 兼容接口。"""

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    timeout: float = 45.0
    max_tokens: int = 2400
    temperature: float = 0.2


@dataclass
class NotifierConfig:
    """告警通道：console / feishu / webhook。"""

    type: str = "console"
    webhook: str = ""
    secret: str = ""
    timeout: float = 5.0
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentConfig:
    """哨兵主循环节奏与去重状态参数。"""

    interval_seconds: float = 60.0
    cooldown_seconds: float = 3600.0
    grace_scans: int = 3
    horizon_seconds: float = 86400.0
    max_lines_per_scan: int = 500
    timezone_hours: float = 8.0


@dataclass
class Config:
    agent: AgentConfig
    logs: list[LogSourceConfig]
    health: HealthConfig
    classifier: ClassifierConfig
    llm: LLMConfig
    notifier: NotifierConfig


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(ENV_PREFIX + name)
        if value:
            return value
    return None


def _str(env_names: tuple[str, ...], fallback: str) -> str:
    value = _env(*env_names)
    return value if value is not None else fallback


def _float(env_names: tuple[str, ...], fallback: float) -> float:
    value = _env(*env_names)
    if value is None:
        return fallback
    try:
        return float(value)
    except ValueError:
        return fallback


def _int(env_names: tuple[str, ...], fallback: int) -> int:
    value = _env(*env_names)
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def _bool(env_names: tuple[str, ...], fallback: bool) -> bool:
    value = _env(*env_names)
    if value is None:
        return fallback
    return value.strip().lower() not in ("0", "false", "no", "off", "")


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("解析 TOML 需要 Python 3.11+")
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def load_dotenv(path: str | Path) -> None:
    """加载 .env 风格的 KEY=VALUE；不执行 shell，不覆盖进程已有环境变量。"""
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: str | Path | None = None) -> Config:
    """读取 TOML 配置并叠加环境变量覆盖，未配置项使用默认值。"""
    data: dict[str, Any] = _read_toml(Path(path)) if path else {}

    agent = _section(data, "agent")
    classifier = _section(data, "classifier")
    llm = _section(data, "llm")
    notifier = _section(data, "notifier")
    health = _section(data, "health")
    logs_data = data.get("logs", [])

    logs: list[LogSourceConfig] = []
    if isinstance(logs_data, list):
        for item in logs_data:
            if isinstance(item, dict) and "path" in item:
                logs.append(
                    LogSourceConfig(
                        path=str(item["path"]),
                        tail_bytes=int(item.get("tail_bytes", 131072)),
                        max_lines=int(item.get("max_lines", 1000)),
                    )
                )

    health_processes = health.get("processes", [])
    health_tcp = health.get("tcp", [])
    if not isinstance(health_processes, list):
        health_processes = []
    if not isinstance(health_tcp, list):
        health_tcp = []
    health_commands: list[CommandProbe] = []
    commands_data = health.get("commands", [])
    if isinstance(commands_data, list):
        for item in commands_data:
            if isinstance(item, dict) and item.get("name"):
                argv = item.get("argv") or item.get("command") or []
                if not isinstance(argv, list):
                    argv = []
                health_commands.append(
                    CommandProbe(
                        name=str(item["name"]),
                        argv=[str(part) for part in argv],
                        shell=str(item.get("shell", "")),
                        cwd=str(item.get("cwd", "")),
                    )
                )

    return Config(
        agent=AgentConfig(
            interval_seconds=_float(("INTERVAL_SECONDS",), float(agent.get("interval_seconds", 60))),
            cooldown_seconds=_float(("COOLDOWN_SECONDS",), float(agent.get("cooldown_seconds", 3600))),
            grace_scans=_int(("GRACE_SCANS",), int(agent.get("grace_scans", 3))),
            horizon_seconds=_float(("HORIZON_SECONDS",), float(agent.get("horizon_seconds", 86400))),
            max_lines_per_scan=_int(("MAX_LINES_PER_SCAN",), int(agent.get("max_lines_per_scan", 500))),
            timezone_hours=_float(("TIMEZONE_HOURS",), float(agent.get("timezone_hours", 8))),
        ),
        logs=logs,
        health=HealthConfig(
            processes=[str(item) for item in health_processes],
            tcp=[str(item) for item in health_tcp],
            commands=health_commands,
        ),
        classifier=ClassifierConfig(
            type=_str(("CLASSIFIER_TYPE",), str(classifier.get("type", "regex"))),
            enabled=_bool(("CLASSIFIER_ENABLED",), bool(classifier.get("enabled", True))),
            threshold=_float(("CLASSIFIER_THRESHOLD",), float(classifier.get("threshold", 0.5))),
            model=_str(("CLASSIFIER_MODEL",), str(classifier.get("model", ""))),
            base_url=_str(("CLASSIFIER_BASE_URL",), str(classifier.get("base_url", ""))),
        ),
        llm=LLMConfig(
            base_url=_str(("LLM_BASE_URL",), str(llm.get("base_url", ""))),
            model=_str(("LLM_MODEL",), str(llm.get("model", ""))),
            api_key=_str(("LLM_API_KEY",), str(llm.get("api_key", ""))),
            timeout=_float(("LLM_TIMEOUT",), float(llm.get("timeout", 45))),
            max_tokens=_int(("LLM_MAX_TOKENS",), int(llm.get("max_tokens", 2400))),
            temperature=_float(("LLM_TEMPERATURE",), float(llm.get("temperature", 0.2))),
        ),
        notifier=NotifierConfig(
            type=_str(("NOTIFIER_TYPE",), str(notifier.get("type", "console"))),
            webhook=_str(("FEISHU_WEBHOOK", "NOTIFIER_WEBHOOK"), str(notifier.get("webhook", ""))),
            secret=_str(("FEISHU_SECRET", "NOTIFIER_SECRET"), str(notifier.get("secret", ""))),
            timeout=_float(("NOTIFIER_TIMEOUT",), float(notifier.get("timeout", 5))),
            headers=dict(notifier.get("headers", {}) or {}),
        ),
    )

