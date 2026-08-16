import asyncio
import tempfile
import unittest
from pathlib import Path

from database import (
    create_account,
    delete_user_tokens,
    add_message,
    create_session,
    get_admin_session,
    get_session,
    init_db,
    list_admin_session_messages,
    list_admin_user_sessions,
    list_account_users,
    list_sessions,
    permanently_delete_deleted_session,
    reset_user_password,
    set_user_role,
    soft_delete_session,
    get_user_by_username,
)
from main import hash_password, verify_password


class AdminDatabaseTests(unittest.TestCase):
    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_existing_ten_li_account_is_the_only_super_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            ten_li = self.run_async(
                create_account(db_path, "十里", "十里", hash_password("old"))
            )
            other = self.run_async(
                create_account(db_path, "other", "other", hash_password("old"))
            )
            self.run_async(init_db(db_path))
            ten_li = self.run_async(get_user_by_username(db_path, "十里"))
            other = self.run_async(get_user_by_username(db_path, "other"))
            self.assertEqual(ten_li["role"], "super_admin")
            self.assertEqual(other["role"], "user")

    def test_admin_listing_excludes_secrets_and_reset_requires_change(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            user = self.run_async(create_account(db_path, "student", "student", hash_password("old")))
            rows = self.run_async(list_account_users(db_path, "student"))
            self.assertEqual(rows[0]["username"], "student")
            self.assertNotIn("password_hash", rows[0])
            self.assertTrue(self.run_async(reset_user_password(db_path, user["id"], hash_password("123"))))
            updated = self.run_async(get_user_by_username(db_path, "student"))
            self.assertTrue(updated["must_change_password"])
            self.assertTrue(verify_password("123", updated["password_hash"]))
            self.run_async(delete_user_tokens(db_path, user["id"]))

    def test_only_super_admin_can_assign_admin_and_super_admin_is_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            user = self.run_async(create_account(db_path, "student", "student", hash_password("old")))
            updated = self.run_async(set_user_role(db_path, user["id"], "admin"))
            self.assertEqual(updated["role"], "admin")
            with self.assertRaises(ValueError):
                self.run_async(set_user_role(db_path, user["id"], "super_admin"))

    def test_read_only_admin_queries_return_sessions_and_full_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            user = self.run_async(create_account(db_path, "student", "student", hash_password("old")))
            session = self.run_async(create_session(db_path, user["id"]))
            self.run_async(add_message(db_path, session["id"], "user", "我的具体内容"))
            self.run_async(add_message(db_path, session["id"], "assistant", "这是只读查看结果"))

            sessions = self.run_async(list_admin_user_sessions(db_path, user["id"]))
            detail = self.run_async(get_admin_session(db_path, session["id"]))
            messages = self.run_async(list_admin_session_messages(db_path, session["id"]))

            self.assertEqual(sessions[0]["message_count"], 2)
            self.assertEqual(detail["username"], "student")
            self.assertEqual([message["content"] for message in messages], ["我的具体内容", "这是只读查看结果"])

    def test_soft_deleted_session_is_hidden_from_user_and_retained_for_super_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            user = self.run_async(create_account(db_path, "student", "student", hash_password("old")))
            session = self.run_async(create_session(db_path, user["id"]))
            self.run_async(add_message(db_path, session["id"], "user", "保留在服务器的消息"))

            self.assertTrue(self.run_async(soft_delete_session(db_path, user["id"], session["id"])))
            self.assertEqual(self.run_async(list_sessions(db_path, user["id"])), [])
            self.assertIsNone(self.run_async(get_session(db_path, user["id"], session["id"])))

            admin_session = self.run_async(get_admin_session(db_path, session["id"]))
            self.assertIsNotNone(admin_session["deleted_at"])
            messages = self.run_async(list_admin_session_messages(db_path, session["id"]))
            self.assertEqual(messages[0]["content"], "保留在服务器的消息")

    def test_only_soft_deleted_session_can_be_permanently_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            user = self.run_async(create_account(db_path, "student", "student", hash_password("old")))
            session = self.run_async(create_session(db_path, user["id"]))
            self.run_async(add_message(db_path, session["id"], "assistant", "待删除的消息"))

            self.assertFalse(self.run_async(permanently_delete_deleted_session(db_path, session["id"])))
            self.assertTrue(self.run_async(soft_delete_session(db_path, user["id"], session["id"])))
            self.assertTrue(self.run_async(permanently_delete_deleted_session(db_path, session["id"])))
            self.assertIsNone(self.run_async(get_admin_session(db_path, session["id"])))
            self.assertEqual(self.run_async(list_admin_session_messages(db_path, session["id"])), [])


if __name__ == "__main__":
    unittest.main()
