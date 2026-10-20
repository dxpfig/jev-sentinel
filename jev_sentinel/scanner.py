"""日志来源扫描（字节偏移增量读取 + 首轮基线）与进程/TCP 健康探测。"""

from __future__ import annotations

import glob
import logging
import socket
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("jev_sentinel.scanner")


def _tail_lines(path: Path, max_bytes: int, max_lines: int) -> list[str]:
    try:
        if not path.is_file():
            return []
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="replace").splitlines()[-max_lines:]
    except OSError:
        return []


class LogSource:
    """单个日志源（支持 glob），记住每个文件的读取偏移，只读新增内容。"""

    def __init__(self, pattern: str, tail_bytes: int = 131072, max_lines: int = 1000) -> None:
        self.pattern = pattern
        self.tail_bytes = tail_bytes
        self.max_lines = max_lines
        self._offsets: dict[Path, int] = {}

    def _expand(self) -> list[Path]:
        return sorted(Path(item) for item in glob.glob(self.pattern))

    def _new_bytes_lines(self, path: Path) -> list[str]:
        try:
            if not path.is_file():
                self._offsets.pop(path, None)
                return []
            size = path.stat().st_size
            offset = self._offsets.get(path, 0)
            if offset > size:  # 文件被轮转或截断
                offset = 0
            with path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read()
            newline = data.rfind(b"\n")
            if newline == -1:
                return []
            self._offsets[path] = offset + newline + 1
            return data[: newline + 1].decode("utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def lines_to_scan(self) -> list[str]:
        """首次接触时基线读尾部，之后只读新增行。"""
        collected: list[str] = []
        for path in self._expand():
            if path in self._offsets:
                lines = self._new_bytes_lines(path)
            else:
                lines = _tail_lines(path, self.tail_bytes, self.max_lines)
                try:
                    self._offsets[path] = path.stat().st_size if path.is_file() else 0
                except OSError:
                    pass
            collected.extend(lines)
        for gone in [path for path in self._offsets if not path.is_file()]:
            self._offsets.pop(gone, None)
        return collected


def process_running(name: str) -> bool | None:
    """判断进程是否在运行；无法确定时返回 None。"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return name.lower() in result.stdout.lower()
        except Exception:
            return None
    try:
        result = subprocess.run(
            ["pgrep", "-f", name], capture_output=True, text=True, timeout=10, check=False
        )
        return result.returncode == 0
    except Exception:
        return None


def tcp_alive(endpoint: str, timeout: float = 3.0) -> bool:
    """判断 host:port 是否可达。"""
    host, _, port_text = endpoint.partition(":")
    try:
        with socket.create_connection((host.strip(), int(port_text)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False

