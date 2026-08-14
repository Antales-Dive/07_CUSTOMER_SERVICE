import unittest
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[1] / "static" / "index.html"


class CompanionUIStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_identity_and_welcome_copy(self):
        required_copy = (
            "<title>有话说</title>",
            "今天过得怎么样？",
            "不用想好怎么说，想到哪儿说到哪儿。",
            "慢慢说，我在听。",
            "最近聊过",
            "重新聊聊",
        )
        for copy in required_copy:
            with self.subTest(copy=copy):
                self.assertIn(copy, self.html)

    def test_all_conversation_modes_are_present(self):
        mode_labels = (
            "我只想吐槽",
            "陪我理一理",
            "帮我想办法",
            "有点撑不住了",
        )
        for label in mode_labels:
            with self.subTest(label=label):
                self.assertIn(label, self.html)

    def test_support_and_privacy_structure_is_present(self):
        required_structure = (
            'id="support-btn"',
            'id="support-dialog"',
            "联系辅导员",
            "预约心理咨询",
            "紧急求助",
            "聊天会保存在会话历史中，但不会自动联系任何人或转交给真人。",
        )
        for item in required_structure:
            with self.subTest(item=item):
                self.assertIn(item, self.html)

    def test_legacy_human_transfer_is_removed(self):
        self.assertNotIn('id="human-btn"', self.html)
        self.assertNotIn("transferHuman", self.html)


if __name__ == "__main__":
    unittest.main()
