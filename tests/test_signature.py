from __future__ import annotations

import unittest

from jev_sentinel.signature import is_error_line, normalize_signature


class SignatureTests(unittest.TestCase):
    def test_error_line_detection(self) -> None:
        self.assertTrue(is_error_line("获取报表数据错误: server ruturn none"))
        self.assertTrue(is_error_line("自选股同步失败，错误码=7"))
        self.assertTrue(is_error_line("Traceback (most recent call last)"))
        self.assertFalse(is_error_line("json: {"))
        self.assertFalse(is_error_line("本轮耗时 30.0s，规则将重新预热"))

    def test_normalize_signature_strips_timestamp_and_uuid(self) -> None:
        line = "2026-10-19 23:52:38 任务 123e4567-e89b-12d3-a456-426614174000 执行失败"
        self.assertEqual(normalize_signature(line), "任务 <id> 执行失败")

    def test_normalize_signature_whitespace(self) -> None:
        self.assertEqual(normalize_signature("  连接   失败  "), "连接 失败")


if __name__ == "__main__":
    unittest.main()

