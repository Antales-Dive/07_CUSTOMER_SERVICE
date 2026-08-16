"""Async SQLite access for users, sessions, messages, and legacy tickets."""

import sqlite3
import uuid
from datetime import datetime, timezone

import aiosqlite


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    mode                TEXT NOT NULL,
    anonymous_id        TEXT UNIQUE,
    username            TEXT,
    normalized_username TEXT UNIQUE,
    password_hash       TEXT,
    role                TEXT NOT NULL DEFAULT 'user',
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    title       TEXT DEFAULT '新会话',
    status      TEXT DEFAULT 'active',
    deleted_at  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    user_message  TEXT NOT NULL,
    priority      TEXT DEFAULT 'medium',
    status        TEXT DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_CREATE_TABLES)
        cur = await db.execute("PRAGMA table_info(users)")
        user_columns = {row[1] for row in await cur.fetchall()}
        if "role" not in user_columns:
            await db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "must_change_password" not in user_columns:
            await db.execute(
                "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
            )
        cur = await db.execute("PRAGMA table_info(sessions)")
        session_columns = {row[1] for row in await cur.fetchall()}
        if "user_id" not in session_columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        if "deleted_at" not in session_columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN deleted_at TEXT")

        legacy_user_id = "legacy-anonymous-user"
        await db.execute(
            "INSERT OR IGNORE INTO users "
            "(id, mode, anonymous_id, created_at) VALUES (?, 'anonymous', ?, ?)",
            (legacy_user_id, "legacy-anonymous", _now()),
        )
        await db.execute(
            "UPDATE sessions SET user_id = ? WHERE user_id IS NULL OR user_id = ''",
            (legacy_user_id,),
        )
        await db.execute(
            "UPDATE users SET role = 'user' WHERE role IS NULL OR role NOT IN ('user', 'admin', 'super_admin')"
        )
        await db.execute(
            "UPDATE users SET role = 'user' WHERE role = 'super_admin' AND normalized_username != ?",
            ("十里",),
        )
        await db.execute(
            "UPDATE users SET role = 'super_admin' WHERE mode = 'account' AND normalized_username = ?",
            ("十里",),
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_one_super_admin "
            "ON users(role) WHERE role = 'super_admin'"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_updated "
            "ON sessions(user_id, updated_at DESC)"
        )
        await db.commit()


async def get_or_create_anonymous_user(db_path: str, anonymous_id: str) -> dict:
    anonymous_id = anonymous_id.strip()
    if not anonymous_id:
        raise ValueError("anonymous_id must not be empty")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE mode = 'anonymous' AND anonymous_id = ?",
            (anonymous_id,),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)

        user = {
            "id": str(uuid.uuid4()),
            "mode": "anonymous",
            "anonymous_id": anonymous_id,
            "username": None,
            "normalized_username": None,
            "password_hash": None,
            "role": "user",
            "must_change_password": 0,
            "created_at": _now(),
        }
        await db.execute(
            "INSERT INTO users "
            "(id, mode, anonymous_id, username, normalized_username, password_hash, role, must_change_password, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(user.values()),
        )
        await db.commit()
        return user


async def create_account(
    db_path: str,
    username: str,
    normalized_username: str,
    password_hash: str,
) -> dict:
    user = {
        "id": str(uuid.uuid4()),
        "mode": "account",
        "anonymous_id": None,
        "username": username,
        "normalized_username": normalized_username,
        "password_hash": password_hash,
        "role": "user",
        "must_change_password": 0,
        "created_at": _now(),
    }
    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(
                "INSERT INTO users "
                "(id, mode, anonymous_id, username, normalized_username, password_hash, role, must_change_password, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(user.values()),
            )
            await db.commit()
        except sqlite3.IntegrityError:
            raise ValueError("username already exists") from None
    return user


async def get_user_by_username(db_path: str, normalized_username: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE normalized_username = ?",
            (normalized_username,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_user_by_id(db_path: str, user_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_account_users(db_path: str, query: str = "") -> list[dict]:
    normalized_query = query.strip().casefold()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        if normalized_query:
            cur = await db.execute(
                "SELECT id, username, role, must_change_password FROM users "
                "WHERE mode = 'account' AND normalized_username LIKE ? "
                "ORDER BY username COLLATE NOCASE",
                (f"%{normalized_query}%",),
            )
        else:
            cur = await db.execute(
                "SELECT id, username, role, must_change_password FROM users "
                "WHERE mode = 'account' ORDER BY username COLLATE NOCASE"
            )
        return [dict(row) for row in await cur.fetchall()]


async def list_admin_user_sessions(
    db_path: str, user_id: str, limit: int = 50, offset: int = 0
) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT s.id, s.title, s.created_at, s.updated_at, s.deleted_at, COUNT(m.id) AS message_count "
            "FROM sessions s LEFT JOIN messages m ON s.id = m.session_id "
            "WHERE s.user_id = ? GROUP BY s.id "
            "ORDER BY s.updated_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        return [dict(row) for row in await cur.fetchall()]


async def get_admin_session(db_path: str, session_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT s.id, s.title, s.created_at, s.updated_at, s.deleted_at, u.id AS user_id, u.username "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
            (session_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_admin_session_messages(db_path: str, session_id: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def set_super_admin_by_username(db_path: str, normalized_username: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE mode = 'account' AND normalized_username = ?",
            (normalized_username,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await db.execute(
            "UPDATE users SET role = 'user' WHERE role = 'super_admin' AND id != ?",
            (row["id"],),
        )
        await db.execute("UPDATE users SET role = 'super_admin' WHERE id = ?", (row["id"],))
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE id = ?", (row["id"],))
        return dict(await cur.fetchone())


async def set_user_role(db_path: str, user_id: str, role: str) -> dict | None:
    if role not in {"user", "admin"}:
        raise ValueError("invalid role")
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute("SELECT * FROM users WHERE id = ? AND mode = 'account'", (user_id,))
        row = await cur.fetchone()
        if not row or row["role"] == "super_admin":
            return None
        await db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return dict(await cur.fetchone())


async def reset_user_password(db_path: str, user_id: str, password_hash: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 1 "
            "WHERE id = ? AND mode = 'account' AND role = 'user'",
            (password_hash, user_id),
        )
        await db.commit()
        return cur.rowcount == 1


async def update_user_password(db_path: str, user_id: str, password_hash: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 "
            "WHERE id = ? AND mode = 'account'",
            (password_hash, user_id),
        )
        await db.commit()
        return cur.rowcount == 1


async def delete_user_tokens(db_path: str, user_id: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        await db.commit()


async def create_auth_token(db_path: str, user_id: str, token_hash: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        await db.execute(
            "INSERT INTO auth_tokens (token_hash, user_id, created_at) VALUES (?, ?, ?)",
            (token_hash, user_id, _now()),
        )
        await db.commit()


async def get_user_by_token(db_path: str, token_hash: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT u.* FROM users u "
            "JOIN auth_tokens t ON t.user_id = u.id "
            "WHERE t.token_hash = ?",
            (token_hash,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_auth_token(db_path: str, token_hash: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
        await db.commit()


async def migrate_anonymous_sessions(
    db_path: str, anonymous_user_id: str, user_id: str
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE sessions SET user_id = ? WHERE user_id = ?",
            (user_id, anonymous_user_id),
        )
        await db.commit()


async def create_session(db_path: str, user_id: str) -> dict:
    session_id = str(uuid.uuid4())
    now = _now()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO sessions (id, user_id, title, status, created_at, updated_at) "
            "VALUES (?, ?, '新会话', 'active', ?, ?)",
            (session_id, user_id, now, now),
        )
        await db.commit()
    return {"id": session_id, "title": "新会话", "created_at": now}


async def list_sessions(db_path: str, user_id: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT s.id, s.title, s.updated_at, COUNT(m.id) AS message_count "
            "FROM sessions s LEFT JOIN messages m ON s.id = m.session_id "
            "WHERE s.user_id = ? AND s.deleted_at IS NULL "
            "GROUP BY s.id ORDER BY s.updated_at DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def get_session(db_path: str, user_id: str, session_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (session_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def soft_delete_session(db_path: str, user_id: str, session_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE sessions SET deleted_at = ? "
            "WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (_now(), session_id, user_id),
        )
        await db.commit()
        return cur.rowcount == 1


async def permanently_delete_deleted_session(db_path: str, session_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute("BEGIN")
            cur = await db.execute(
                "SELECT id FROM sessions WHERE id = ? AND deleted_at IS NOT NULL", (session_id,)
            )
            if not await cur.fetchone():
                await db.rollback()
                return False
            await db.execute("DELETE FROM tickets WHERE session_id = ?", (session_id,))
            await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            await db.execute("DELETE FROM sessions WHERE id = ? AND deleted_at IS NOT NULL", (session_id,))
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise


async def update_session_title(db_path: str, session_id: str, title: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), session_id),
        )
        await db.commit()


async def touch_session(db_path: str, session_id: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await db.commit()


async def add_message(db_path: str, session_id: str, role: str, content: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )
        await db.commit()


async def get_messages(db_path: str, session_id: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def create_ticket(
    db_path: str, session_id: str, user_message: str, priority: str = "medium"
) -> dict:
    ticket_id = str(uuid.uuid4())
    now = _now()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO tickets (id, session_id, user_message, priority, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (ticket_id, session_id, user_message, priority, now, now),
        )
        await db.commit()
    return {
        "id": ticket_id,
        "session_id": session_id,
        "user_message": user_message,
        "priority": priority,
        "status": "pending",
        "created_at": now,
    }


async def list_tickets(db_path: str, user_id: str | None = None) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        if user_id:
            cur = await db.execute(
                "SELECT t.id, t.session_id, t.user_message, t.status, t.priority, t.created_at "
                "FROM tickets t JOIN sessions s ON s.id = t.session_id "
                "WHERE s.user_id = ? ORDER BY t.created_at DESC",
                (user_id,),
            )
        else:
            cur = await db.execute(
                "SELECT id, session_id, user_message, status, priority, created_at "
                "FROM tickets ORDER BY created_at DESC"
            )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]
