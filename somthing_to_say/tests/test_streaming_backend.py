import json
import unittest
from pathlib import Path

from main import _extract_stream_content, sse_event


class StreamingContractTests(unittest.TestCase):
    def test_stream_parser_reads_langgraph_model_updates(self):
        chunk = {
            "model": {
                "messages": [
                    {"content": "这是一条动态回复。"},
                ],
            },
        }

        self.assertEqual(_extract_stream_content(chunk), "这是一条动态回复。")

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
