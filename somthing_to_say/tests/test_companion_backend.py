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


def declared_requirement_names() -> set[str]:
    names: set[str] = set()
    for line in read_source("requirements.txt").splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#"):
            continue
        name = requirement.split(";", 1)[0].split("[", 1)[0]
        for marker in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            name = name.split(marker, 1)[0]
        names.add(name.strip().lower())
    return names


class CompanionBackendSafetyContractTests(unittest.TestCase):
    def test_runtime_dependencies_are_declared(self):
        requirements = declared_requirement_names()

        for dependency in ("fastapi", "uvicorn", "aiosqlite", "pydantic"):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, requirements)

    def test_mcp_sdk_is_constrained_below_major_two(self):
        requirements = read_source("requirements.txt")

        self.assertIn("mcp>=1.9.2,<2.0", requirements)

    def test_mcp_launcher_uses_the_read_only_python_server(self):
        main_source = read_source("main.py")

        self.assertIn('"zzu_official"', main_source)
        self.assertIn('"command": sys.executable', main_source)
        self.assertIn('"zzu_campus_mcp.py"', main_source)
        self.assertNotIn("@modelcontextprotocol/server-filesystem", main_source)
        self.assertNotIn('"write_file"', main_source)

    def test_app_identity_uses_companion_name(self):
        main_source = read_source("main.py")
        tree = ast.parse(main_source, filename="main.py")

        fastapi_titles = [
            keyword.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "FastAPI"
            for keyword in node.keywords
            if keyword.arg == "title"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ]
        self.assertIn("有话说", fastapi_titles)

    def test_rag_uses_neutral_knowledge_base_identity(self):
        rag_source = read_source("rag.py")

        self.assertNotIn("客服 FAQ", rag_source)
        self.assertIn("搜索已配置的常见问题知识库，获取标准答案。", rag_source)

    def test_system_prompt_contains_approved_safety_language(self):
        prompt = assigned_string_constants("config.py")["SYSTEM_PROMPT"]

        required_phrases = (
            "有话说",
            "先回应用户具体表达出的感受",
            "询问用户更需要倾听、梳理还是建议",
            "不进行心理疾病诊断或治疗",
            "找真人聊聊",
            "不能声称已经联系任何人",
            "郑州大学官网公开资料",
            "引用工具返回的官方链接",
            "不要猜测或编造校内规定",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)
        self.assertNotIn("情绪陪伴对话不调用任何工具", prompt)
        self.assertIn("校园资料工具", prompt)

    def test_system_prompt_covers_urgent_safety_paths(self):
        prompt = assigned_string_constants("config.py")["SYSTEM_PROMPT"]

        required_phrases = (
            "自伤、自杀或伤害他人的意图、计划、时间或方法",
            "正在遭受暴力或严重失控",
            "停止普通建议",
            "先确认用户当前是否安全",
            "可信任的身边人",
            "经过核实的学校支持",
            "当地紧急服务",
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
        parameter_names = [
            parameter.arg
            for parameter in (
                *build_agent.args.posonlyargs,
                *build_agent.args.args,
                *build_agent.args.kwonlyargs,
            )
        ]
        self.assertIn("session_id", parameter_names)

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

        tool_calls = [
            node
            for node in ast.walk(build_agent)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "tools"
        ]
        call_contracts = {
            (
                call.func.attr,
                tuple(
                    argument.id if isinstance(argument, ast.Name) else None
                    for argument in call.args
                ),
            )
            for call in tool_calls
        }
        self.assertIn(("append", ("rag_tool",)), call_contracts)
        self.assertIn(("extend", ("mcp_tools",)), call_contracts)

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

    def test_direct_launcher_uses_awaitable_uvicorn_server(self):
        source = read_source("main.py")
        launcher = source.split('if __name__ == "__main__":', 1)[1]

        self.assertIn("server = uvicorn.Server", launcher)
        self.assertIn("await server.serve()", launcher)
        self.assertNotIn("uvicorn.run(app", launcher)
        self.assertNotIn("async with lifespan(app)", launcher)


if __name__ == "__main__":
    unittest.main()
