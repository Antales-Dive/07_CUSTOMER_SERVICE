import unittest
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]


class ProblemSolvingContractTests(unittest.TestCase):
    def test_prompt_is_natural_and_action_oriented(self):
        source = (ROOT / "config.py").read_text(encoding="utf-8")
        self.assertIn("PROBLEM_SOLVING_PROMPT", source)
        self.assertIn("不强制固定格式", source)
        self.assertNotIn("最多给出 2 个方案", source)
        self.assertNotIn("必须明确给出“今天的第一步”", source)
        self.assertIn("不提供医疗诊断或治疗、法律定论、投资建议", source)

    def test_problem_solving_agent_keeps_available_tools(self):
        source = (ROOT / "agent_factory.py").read_text(encoding="utf-8")
        self.assertIn("tools = [get_weather, query_order]", source)
        self.assertIn("if rag_tool is not None:", source)
        self.assertIn("if mcp_tools:", source)
        self.assertIn("tools.extend(mcp_tools)", source)
        self.assertNotIn('mode != "problem_solving"', source)
        self.assertNotIn("tools = []", source)
        self.assertIn("PROBLEM_SOLVING_PROMPT", source)

    def test_problem_solving_mode_can_use_faq_and_official_sources(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        config_source = (ROOT / "config.py").read_text(encoding="utf-8")
        problem_solving_prompt = config_source.partition("PROBLEM_SOLVING_PROMPT")[2]

        self.assertIn("if should_use_knowledge_base(content):", main_source)
        self.assertNotIn('mode == "companion" and should_use_knowledge_base(content)', main_source)
        self.assertIn("郑州大学官网公开资料", problem_solving_prompt)
        self.assertIn("引用工具返回的官方链接", problem_solving_prompt)

    def test_chat_request_defaults_to_companion_mode(self):
        from models import ChatRequest

        self.assertEqual(ChatRequest(content="帮我想想").mode, "companion")
        self.assertEqual(ChatRequest(content="帮我想想", mode="problem_solving").mode, "problem_solving")
        with self.assertRaises(ValidationError):
            ChatRequest(content="我很难受", mode="urgent")


if __name__ == "__main__":
    unittest.main()
