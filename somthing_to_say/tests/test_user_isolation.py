import asyncio
import tempfile
import unittest
from pathlib import Path

from database import (
    add_message,
    create_account,
    create_session,
    get_or_create_anonymous_user,
    get_session,
    get_user_by_username,
    init_db,
    list_sessions,
    migrate_anonymous_sessions,
)
from main import hash_password, normalize_username, verify_password
from models import AuthRequest


class UserIsolationDatabaseTests(unittest.TestCase):
    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_users_only_see_their_own_sessions_and_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            user_a = self.run_async(get_or_create_anonymous_user(db_path, "browser-a"))
            user_b = self.run_async(get_or_create_anonymous_user(db_path, "browser-b"))
            session_a = self.run_async(create_session(db_path, user_a["id"]))
            session_b = self.run_async(create_session(db_path, user_b["id"]))
            self.run_async(add_message(db_path, session_a["id"], "user", "只属于 A"))

            sessions_a = self.run_async(list_sessions(db_path, user_a["id"]))
            sessions_b = self.run_async(list_sessions(db_path, user_b["id"]))

            self.assertEqual([row["id"] for row in sessions_a], [session_a["id"]])
            self.assertEqual([row["id"] for row in sessions_b], [session_b["id"]])
            self.assertIsNotNone(
                self.run_async(get_session(db_path, user_a["id"], session_a["id"]))
            )
            self.assertIsNone(
                self.run_async(get_session(db_path, user_b["id"], session_a["id"]))
            )

    def test_anonymous_sessions_can_be_migrated_to_an_account(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            anonymous = self.run_async(get_or_create_anonymous_user(db_path, "browser-a"))
            account = self.run_async(get_or_create_anonymous_user(db_path, "account-user"))
            session = self.run_async(create_session(db_path, anonymous["id"]))

            self.run_async(migrate_anonymous_sessions(db_path, anonymous["id"], account["id"]))

            self.assertIsNone(
                self.run_async(get_session(db_path, anonymous["id"], session["id"]))
            )
            self.assertIsNotNone(
                self.run_async(get_session(db_path, account["id"], session["id"]))
            )

    def test_anonymous_identity_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))

            first = self.run_async(get_or_create_anonymous_user(db_path, "browser-a"))
            second = self.run_async(get_or_create_anonymous_user(db_path, "browser-a"))

            self.assertEqual(first["id"], second["id"])

    def test_account_username_is_case_insensitive_and_password_is_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "test.db")
            self.run_async(init_db(db_path))
            display_name, normalized = normalize_username("  Student  ")
            stored_hash = hash_password("a!2")
            account = self.run_async(
                create_account(db_path, display_name, normalized, stored_hash)
            )

            self.assertEqual(account["username"], "Student")
            self.assertEqual(
                self.run_async(get_user_by_username(db_path, "student"))["id"],
                account["id"],
            )
            self.assertTrue(verify_password("a!2", stored_hash))
            self.assertFalse(verify_password("wrong", stored_hash))
            self.assertNotEqual(stored_hash, "a!2")
            with self.assertRaises(ValueError):
                self.run_async(create_account(db_path, "Other", "student", hash_password("b")))

    def test_password_request_accepts_all_characters_but_caps_length_at_ten(self):
        AuthRequest(username="student", password="a1!中")
        with self.assertRaises(ValueError):
            AuthRequest(username="student", password="12345678901")


if __name__ == "__main__":
    unittest.main()
