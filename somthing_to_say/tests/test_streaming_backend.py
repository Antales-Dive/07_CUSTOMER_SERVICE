import json
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from main import _extract_agent_answer, _extract_stream_content, _extract_tool_progress, sse_event


class StreamingContractTests(unittest.TestCase):
    def test_stream_parser_reads_langgraph_model_updates(self):
        chunk = {
            "model": {
                "messages": [
                    AIMessage(content="这是一条动态回复。"),
                ],
            },
        }

        self.assertEqual(_extract_stream_content(chunk), "这是一条动态回复。")

    def test_stream_parser_does_not_render_tool_results_as_answer_text(self):
        tool_message = ToolMessage(
            content='{"sources":[{"title":"办事大厅"}]}',
            tool_call_id="call-1",
            name="list_zzu_official_sources",
        )

        self.assertEqual(
            _extract_stream_content({"tools": {"messages": [tool_message]}}),
            "",
        )

    def test_json_answer_uses_assistant_message_not_tool_result(self):
        tool_message = ToolMessage(
            content='{"sources":[{"title":"办事大厅"}]}',
            tool_call_id="call-1",
            name="list_zzu_official_sources",
        )
        assistant_message = AIMessage(content="最终答案")

        self.assertEqual(
            _extract_agent_answer({"messages": [tool_message, assistant_message]}),
            "最终答案",
        )

    def test_stream_parser_hides_assistant_tool_call_preamble(self):
        message = AIMessage(
            content="我先查询一下。",
            tool_calls=[
                {
                    "name": "search_zzu_official_site",
                    "args": {"query": "办事大厅"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        )

        self.assertEqual(_extract_stream_content({"model": {"messages": [message]}}), "")

    def test_tool_progress_contains_status_without_raw_result(self):
        started = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_zzu_official_site",
                    "args": {"query": "办事大厅"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        )
        completed = ToolMessage(
            content='{"sources":[{"title":"办事大厅"}]}',
            tool_call_id="call-1",
            name="search_zzu_official_site",
        )

        self.assertEqual(
            _extract_tool_progress({"model": {"messages": [started]}}),
            [
                {
                    "call_id": "call-1",
                    "tool": "search_zzu_official_site",
                    "status": "running",
                    "label": "搜索郑州大学官网",
                }
            ],
        )
        progress = _extract_tool_progress({"tools": {"messages": [completed]}})
        self.assertEqual(progress[0]["status"], "completed")
        self.assertNotIn("sources", json.dumps(progress, ensure_ascii=False))

    def test_sse_event_is_structured_json(self):
        event = sse_event("delta", {"text": "你好"})
        self.assertTrue(event.startswith("event: delta\ndata: "))
        payload = json.loads(event.split("data: ", 1)[1].split("\n", 1)[0])
        self.assertEqual(payload["text"], "你好")

    def test_stream_endpoint_has_safe_event_lifecycle(self):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn('/api/chat/{session_id}/stream', source)
        self.assertIn('sse_event("start"', source)
        self.assertIn('sse_event("delta"', source)
        self.assertIn('sse_event("tool"', source)
        self.assertIn('sse_event("done"', source)
        self.assertIn("asyncio.CancelledError", source)
        self.assertIn("scan_output_window", source)

    def test_admin_message_endpoints_are_super_admin_only(self):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn('/api/admin/users/{user_id}/sessions', source)
        self.assertIn('/api/admin/sessions/{session_id}/messages', source)
        self.assertGreaterEqual(source.count("await _require_super_admin(request)"), 3)


if __name__ == "__main__":
    unittest.main()
