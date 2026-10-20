"""命令行入口：加载配置、组装组件、单轮调试或常驻运行。"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .agent import Sentinel
from .classify import build_classifier
from .config import Config, load_config, load_dotenv
from .llm import LLMClient
from .notifier import build_notifier

logger = logging.getLogger("jev_sentinel")


def _resolve_config_path(args: argparse.Namespace) -> Path | None:
    if args.config:
        return Path(args.config)
    env_path = os.environ.get("JEV_SENTINEL_CONFIG")
    if env_path:
        return Path(env_path)
    for candidate in (Path("config.toml"), Path("jev-sentinel.toml")):
        if candidate.is_file():
            return candidate
    return None


def _make_diagnoser(llm: LLMClient):
    def diagnose(snippet: str):
        try:
            return llm.diagnose_logs(snippet)
        except Exception:
            logger.exception("LLM 诊断失败，退回原始日志")
            return None

    return diagnose


def build_sentinel(cfg: Config) -> Sentinel:
    llm = LLMClient(
        cfg.llm.base_url,
        cfg.llm.model,
        cfg.llm.api_key,
        cfg.llm.timeout,
        cfg.llm.max_tokens,
        cfg.llm.temperature,
    )
    return Sentinel(
        agent=cfg.agent,
        logs=cfg.logs,
        health=cfg.health,
        classifier=build_classifier(cfg.classifier),
        diagnoser=_make_diagnoser(llm),
        notifier=build_notifier(cfg.notifier),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="通用日志运维哨兵：本地小模型 + LLM 诊断 + 飞书/webhook 告警")
    parser.add_argument("--config", help="TOML 配置文件路径（默认查找 ./config.toml）")
    parser.add_argument("--env-file", help=".env 风格环境变量文件（默认自动加载当前目录 .env）")
    parser.add_argument("--once", action="store_true", help="只扫描一轮后退出，便于调试")
    parser.add_argument("--log-file", help="可选：把运行日志同时写入该文件")
    parser.add_argument("--version", action="version", version=f"jev-sentinel {__version__}")
    args = parser.parse_args(argv)

    env_file = Path(args.env_file) if args.env_file else (Path(".env") if Path(".env").is_file() else None)
    if env_file:
        try:
            load_dotenv(env_file)
        except OSError as error:
            print(f"读取环境变量文件失败：{error}", file=sys.stderr)
            return 2

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
    )

    try:
        config_path = _resolve_config_path(args)
        cfg = load_config(config_path)
    except Exception as error:
        logger.error("配置加载失败：%s", error)
        return 2

    if not cfg.logs:
        logger.warning("未配置任何日志源（logs 为空），只做健康探测。")

    sentinel = build_sentinel(cfg)
    if args.once:
        sentinel.scan_once()
    else:
        sentinel.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

