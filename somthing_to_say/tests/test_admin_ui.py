import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminUIStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")

    def test_page_contains_restricted_account_controls(self):
        for text in ("账号管理", "搜索用户名", "重置密码", "管理员权限"):
            with self.subTest(text=text):
                self.assertIn(text, self.html)
        self.assertIn("/api/admin/users", self.html)
        self.assertIn("/api/admin/users/", self.html)

    def test_page_does_not_use_regular_user_chat_apis(self):
        self.assertNotIn("/api/sessions", self.html)
        self.assertNotIn("/api/chat/", self.html)

    def test_super_admin_can_open_read_only_session_and_message_view(self):
        for item in (
            "/api/admin/users/",
            "/sessions?limit=",
            "/api/admin/sessions/",
            "showUserSessions",
            "showSessionMessages",
            "总管只读查看会话和完整消息",
            "返回账号列表",
        ):
            with self.subTest(item=item):
                self.assertIn(item, self.html)
        self.assertIn("currentIsSuperAdmin", self.html)

    def test_super_admin_can_identify_and_clear_only_user_deleted_sessions(self):
        self.assertIn("已被用户删除", self.html)
        self.assertIn("session.deleted_at", self.html)
        self.assertIn("permanentlyDeleteSession", self.html)
        self.assertIn("/api/admin/sessions/", self.html)
        self.assertIn("method: 'DELETE'", self.html)


if __name__ == "__main__":
    unittest.main()
