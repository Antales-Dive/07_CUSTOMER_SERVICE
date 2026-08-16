import unittest
from pathlib import Path

import rag


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeRetrievalTests(unittest.TestCase):
    def test_emotional_conversation_does_not_trigger_retrieval(self):
        self.assertFalse(rag.should_use_knowledge_base("今天被老师批评了，我很难受"))

    def test_school_facts_trigger_retrieval(self):
        for content in (
            "学校心理中心怎么预约？",
            "辅导员联系方式在哪里查？",
            "请假流程是什么？",
            "奖学金评定规定是什么？",
        ):
            with self.subTest(content=content):
                self.assertTrue(rag.should_use_knowledge_base(content))

    def test_agent_loads_bounded_runtime_guidance_from_project_skill(self):
        source = (ROOT / "agent_factory.py").read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "campus-emotional-support" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("load_runtime_support_guidance", source)
        self.assertIn("RUNTIME_GUIDANCE_START", source)
        self.assertIn("## Runtime Guidance", skill)


if __name__ == "__main__":
    unittest.main()
