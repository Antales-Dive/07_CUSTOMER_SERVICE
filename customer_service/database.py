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
        cur = await db.execute("PRAGMA table_info(sessions)")
        session_columns = {row[1] for row in await cur.fetchall()}
        if "user_id" not in session_columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")

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
            "created_at": _now(),
        }
        await db.execute(
            "INSERT INTO users "
            "(id, mode, anonymous_id, username, normalized_username, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        "created_at": _now(),
    }
    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(
                "INSERT INTO users "
                "(id, mode, anonymous_id, username, normalized_username, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
            "WHERE s.user_id = ? "
            "GROUP BY s.id ORDER BY s.updated_at DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def get_session(db_path: str, user_id: str, session_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        cur = await db.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


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
