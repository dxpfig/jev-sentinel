"""日志行判定与签名归一化：剥离时间戳等易变字段，得到稳定的去重签名。"""

from __future__ import annotations

import re
from typing import Pattern, Sequence

ERROR_RE = re.compile(
    r"错误|失败|异常|traceback|\berror\b|ruturn none|return none", re.IGNORECASE
)
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_IGNORABLE_PREFIXES = ("json:", "{", "}", '"')


def is_ignorable_line(line: str) -> bool:
    """把明显不是日志消息的行（行情 JSON 数据、空行等）排除在判断之外。"""
    text = line.strip()
    return not text or text.startswith(_IGNORABLE_PREFIXES)


def is_error_line(line: str) -> bool:
    """正则兜底：判断一行日志是否疑似异常。"""
    if is_ignorable_line(line):
        return False
    return bool(ERROR_RE.search(line.strip()))


def normalize_signature(
    line: str, redactions: Sequence[tuple[Pattern[str], str]] | None = None
) -> str:
    """把时间戳、UUID 等易变部分归一化，得到稳定的错误签名。"""
    text = _TIMESTAMP_RE.sub("", line)
    text = _UUID_RE.sub("<id>", text)
    for pattern, replacement in redactions or []:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()

