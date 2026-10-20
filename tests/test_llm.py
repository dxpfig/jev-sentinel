from __future__ import annotations

import unittest

from jev_sentinel.llm import _first_json_object, _validated_diagnosis, extract_json_object


class JsonExtractionTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(extract_json_object('{"a": 1}'), {"a": 1})

    def test_think_block(self) -> None:
        content = "<think>让我想想</think>\n{\"summary\": \"故障\"}"
        self.assertEqual(extract_json_object(content), {"summary": "故障"})

    def test_code_fence(self) -> None:
        content = "```json\n{\"summary\": \"故障\"}\n```"
        self.assertEqual(extract_json_object(content), {"summary": "故障"})

    def test_first_json_object_with_surrounding_text(self) -> None:
        content = "结论如下 {\"summary\": \"故障\"} 仅供参考"
        self.assertEqual(extract_json_object(content), {"summary": "故障"})

    def test_non_json_returns_none(self) -> None:
        self.assertIsNone(extract_json_object("没有 JSON"))

    def test_first_json_object_handles_escaped_quotes(self) -> None:
        text = 'x {"a": "带\\"引号\\"的值"} y'
        self.assertEqual(_first_json_object(text), '{"a": "带\\"引号\\"的值"}')


class DiagnosisValidationTests(unittest.TestCase):
    def test_valid_diagnosis(self) -> None:
        result = _validated_diagnosis(
            '{"summary": "接口异常", "cause": "服务掉线", "suggestion": "重启", "severity": "high"}'
        )
        self.assertEqual(result["summary"], "接口异常")
        self.assertEqual(result["severity"], "high")

    def test_invalid_severity_falls_back(self) -> None:
        result = _validated_diagnosis('{"summary": "x", "severity": "critical"}')
        self.assertEqual(result["severity"], "unknown")


if __name__ == "__main__":
    unittest.main()

