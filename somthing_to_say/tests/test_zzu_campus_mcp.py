import unittest

from config import ZZU_MAX_RESPONSE_BYTES
from zzu_campus_mcp import (
    TOOL_NAMES,
    extract_page_text,
    fetch_official_page,
    validate_official_url,
)


class FakeHeaders:
    def __init__(self, content_type: str = "text/html; charset=utf-8", location: str = ""):
        self.content_type = content_type
        self.location = location

    def get_content_type(self) -> str:
        return self.content_type.split(";", 1)[0]

    def get_content_charset(self) -> str | None:
        if "charset=" not in self.content_type:
            return None
        return self.content_type.split("charset=", 1)[1]

    def get(self, name: str, default: str | None = None) -> str | None:
        if name.lower() == "location":
            return self.location or default
        return default


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"<html><title>notice</title><body>content</body></html>",
        content_type: str = "text/html; charset=utf-8",
        location: str = "",
    ):
        self.status = status
        self.headers = FakeHeaders(content_type, location)
        self.body = body

    def read(self, size: int) -> bytes:
        return self.body[:size]


class FakeOpener:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.requests = []

    def __call__(self, request, timeout: float):
        self.requests.append((request, timeout))
        return self.response


class OfficialUrlValidationTests(unittest.TestCase):
    def test_accepts_root_domain_and_subdomain(self):
        self.assertEqual(
            validate_official_url("https://www.zzu.edu.cn/news.htm"),
            "https://www.zzu.edu.cn/news.htm",
        )
        self.assertEqual(
            validate_official_url("http://jwc.zzu.edu.cn/"),
            "http://jwc.zzu.edu.cn/",
        )

    def test_rejects_external_and_unsafe_urls(self):
        for value in (
            "https://example.com/",
            "https://zzu.edu.cn.evil.example/",
            "https://127.0.0.1/",
            "file:///etc/passwd",
            "https://user@www.zzu.edu.cn/",
            "https://www.zzu.edu.cn:8443/",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_official_url(value)


class HtmlExtractionTests(unittest.TestCase):
    def test_ignores_scripts_and_styles(self):
        page = extract_page_text(
            "<html><head><title>通知</title><style>hidden</style></head>"
            "<body><script>secret</script><main>选课安排</main></body></html>"
        )

        self.assertEqual(page["title"], "通知")
        self.assertIn("选课安排", page["text"])
        self.assertNotIn("hidden", page["text"])
        self.assertNotIn("secret", page["text"])


class OfficialFetchTests(unittest.TestCase):
    def test_rejects_cross_domain_redirect(self):
        opener = FakeOpener(
            FakeResponse(status=302, location="https://example.com/next")
        )

        with self.assertRaises(ValueError):
            fetch_official_page("https://www.zzu.edu.cn/a.htm", opener=opener)

    def test_rejects_non_html_and_oversized_responses(self):
        with self.assertRaises(ValueError):
            fetch_official_page(
                "https://www.zzu.edu.cn/a.htm",
                opener=FakeOpener(FakeResponse(content_type="application/pdf")),
            )
        with self.assertRaises(ValueError):
            fetch_official_page(
                "https://www.zzu.edu.cn/a.htm",
                opener=FakeOpener(FakeResponse(body=b"x" * (ZZU_MAX_RESPONSE_BYTES + 1))),
            )

    def test_declares_only_read_only_tools(self):
        self.assertEqual(
            set(TOOL_NAMES),
            {
                "search_zzu_official_site",
                "read_zzu_official_page",
                "list_zzu_official_sources",
            },
        )


if __name__ == "__main__":
    unittest.main()
