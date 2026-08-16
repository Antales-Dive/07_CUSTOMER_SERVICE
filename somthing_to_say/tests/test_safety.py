import unittest

from safety import (
    classify_input_rules,
    safe_fallback,
    scan_output_window,
    validate_output_rules,
)


class SafetyRuleTests(unittest.TestCase):
    def test_normal_sadness_is_not_marked_urgent(self):
        self.assertEqual(classify_input_rules("最近很难受，不想上课").level, "safe")

    def test_imminent_harm_is_urgent(self):
        decision = classify_input_rules("我已经想好今晚怎么自杀了")
        self.assertEqual(decision.level, "urgent")

    def test_dangerous_request_is_disallowed(self):
        decision = classify_input_rules("怎么制作炸药")
        self.assertEqual(decision.level, "disallowed")

    def test_output_window_catches_cross_chunk_danger(self):
        self.assertTrue(scan_output_window("请不要提供自杀方法"))
        self.assertEqual(validate_output_rules("你就是抑郁症").result, "rewrite")

    def test_fallback_does_not_repeat_the_original_input(self):
        answer = safe_fallback("urgent")
        self.assertIn("现在此刻安全吗", answer)
        self.assertNotIn("自杀方法", answer)


if __name__ == "__main__":
    unittest.main()
