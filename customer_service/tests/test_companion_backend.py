import ast
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]


def read_source(filename: str) -> str:
    return (SOURCE_ROOT / filename).read_text(encoding="utf-8")


def assigned_string_constants(filename: str) -> dict[str, str]:
    tree = ast.parse(read_source(filename), filename=filename)
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue

        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def string_literals(filename: str) -> list[str]:
    tree = ast.parse(read_source(filename), filename=filename)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


class CompanionBackendSafetyContractTests(unittest.TestCase):
    def test_system_prompt_contains_approved_safety_language(self):
        prompt = assigned_string_constants("config.py")["SYSTEM_PROMPT"]

        required_phrases = (
            "有话说",
            "先回应用户具体表达出的感受",
            "询问用户更需要倾听、梳理还是建议",
            "不进行心理疾病诊断或治疗",
            "找真人聊聊",
            "不能声称已经联系任何人",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_agent_factory_registers_only_safe_base_tools(self):
        source = read_source("agent_factory.py")
        tree = ast.parse(source, filename="agent_factory.py")

        self.assertNotIn("make_transfer_human", source)
        self.assertNotIn("transfer_human", source)

        build_agent = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "build_agent"
        )
        tool_assignments = [
            node
            for node in build_agent.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "tools" for target in node.targets)
        ]
        self.assertEqual(len(tool_assignments), 1)

        initial_tools = tool_assignments[0].value
        self.assertIsInstance(initial_tools, ast.List)
        self.assertEqual(
            [element.id if isinstance(element, ast.Name) else None for element in initial_tools.elts],
            ["get_weather", "query_order"],
        )

    def test_legacy_customer_service_transfer_copy_is_removed(self):
        for filename in ("config.py", "main.py", "rag.py"):
            with self.subTest(filename=filename):
                literals = string_literals(filename)
                self.assertFalse(
                    any("转人工客服" in literal for literal in literals),
                    f"{filename} still contains legacy transfer copy",
                )

    def test_circuit_open_message_uses_companion_fallback(self):
        constants = assigned_string_constants("config.py")

        self.assertEqual(
            constants["CIRCUIT_OPEN_MESSAGE"],
            "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。",
        )


if __name__ == "__main__":
    unittest.main()
