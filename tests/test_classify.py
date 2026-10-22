from __future__ import annotations

import unittest

from jev_sentinel.classify import JevStyleClassifier, RegexClassifier


class ClassifierSkipTests(unittest.TestCase):
    def test_regex_skips_json_data_line(self) -> None:
        self.assertFalse(RegexClassifier().is_anomaly('json: {"ErrorId":"0"}')[0])

    def test_jev_skips_json_data_line_without_loading_model(self) -> None:
        classifier = JevStyleClassifier(threshold=0.5)
        self.assertEqual(classifier.is_anomaly('json: {"ErrorId":"0"}'), (False, None, "skip"))


if __name__ == "__main__":
    unittest.main()
