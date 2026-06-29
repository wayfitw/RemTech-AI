"""SQLite-слой. Портирован из mybot (agent/memory.py), адаптирован под веб:
users, conversations, chat_history, uploaded_files, activity_log."""
import json
import sqlite3
from datetime import datetime
from typing import Any

from config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                full_name   TEXT,
                password_hash TEXT,
                role        TEXT NOT NULL DEFAULT 'user',   -- admin | user
                active      INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            c.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
        except sqlite3.OperationalError:
            pass
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                title       TEXT DEFAULT 'Новый чат',
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                user_id         INTEGER NOT NULL REFERENCES users(id),
                role            TEXT NOT NULL,        -- user | assistant
                content         TEXT NOT NULL,        -- JSON
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER REFERENCES conversations(id),
                user_id         INTEGER NOT NULL REFERENCES users(id),
                kind            TEXT,                 -- docx | pptx | xlsx | pdf | image | other
                file_name       TEXT NOT NULL,
                file_path       TEXT NOT NULL,        -- путь на диске
                direction       TEXT NOT NULL DEFAULT 'upload',  -- upload | output
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER REFERENCES users(id),
                action      TEXT NOT NULL,
                detail      TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.commit()


# ── Users ──────────────────────────────────────────────────────────────────────

def get_or_create_user(username: str, role: str = "user") -> dict:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row:
            return dict(row)
        cur = c.execute(
            "INSERT INTO users (username, role) VALUES (?, ?)", (username, role)
        )
        c.commit()
        return {"id": cur.lastrowid, "username": username, "role": role, "active": 1}


def get_user(user_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def create_user(username: str, password_hash: str, role: str = "user",
                full_name: str = "") -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO users (username, full_name, password_hash, role) "
            "VALUES (?, ?, ?, ?)",
            (username, full_name, password_hash, role),
        )
        c.commit()
        return {"id": cur.lastrowid, "username": username, "full_name": full_name,
                "role": role, "active": 1}


def count_registered_users() -> int:
    """Число реальных аккаунтов (с паролем) — для назначения первого админом."""
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM users WHERE password_hash IS NOT NULL"
        ).fetchone()
    return row[0]


def list_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, username, full_name, role, active, created_at FROM users "
            "WHERE password_hash IS NOT NULL ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def set_user_active(user_id: int, active: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
        c.commit()


def update_password(user_id: int, password_hash: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
        c.commit()


# ── Conversations ────────────────────────────────────────────────────────────

def create_conversation(user_id: int, title: str = "Новый чат") -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, title)
        )
        c.commit()
        return {"id": cur.lastrowid, "user_id": user_id, "title": title}


def list_conversations(user_id: int, limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(conversation_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
    return dict(row) if row else None


def set_conversation_title(conversation_id: int, title: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE conversations SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (title, conversation_id),
        )
        c.commit()


def touch_conversation(conversation_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (conversation_id,),
        )
        c.commit()


def delete_conversation(conversation_id: int, user_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM chat_history WHERE conversation_id=?", (conversation_id,))
        c.execute("DELETE FROM uploaded_files WHERE conversation_id=?", (conversation_id,))
        c.execute(
            "DELETE FROM conversations WHERE id=? AND user_id=?",
            (conversation_id, user_id),
        )
        c.commit()


# ── Chat history ─────────────────────────────────────────────────────────────

def save_message(conversation_id: int, user_id: int, role: str, content: Any) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO chat_history (conversation_id, user_id, role, content) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, user_id, role, json.dumps(content, ensure_ascii=False)),
        )
        c.commit()


def load_history(conversation_id: int, limit: int = 40) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM chat_history WHERE conversation_id=? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    result = []
    for r in reversed(rows):
        try:
            content = json.loads(r["content"])
        except Exception:
            content = r["content"]
        result.append({"role": r["role"], "content": content})
    return result


# ── Uploaded / generated files ───────────────────────────────────────────────

def save_file_record(
    user_id: int,
    file_name: str,
    file_path: str,
    kind: str = "other",
    conversation_id: int | None = None,
    direction: str = "upload",
) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO uploaded_files "
            "(conversation_id, user_id, kind, file_name, file_path, direction) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, user_id, kind, file_name, file_path, direction),
        )
        c.commit()
        return cur.lastrowid


def get_file_record(file_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM uploaded_files WHERE id=?", (file_id,)).fetchone()
    return dict(row) if row else None


def get_last_uploaded(conversation_id: int, kind: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM uploaded_files WHERE conversation_id=? AND kind=? "
            "AND direction='upload' ORDER BY id DESC LIMIT 1",
            (conversation_id, kind),
        ).fetchone()
    return dict(row) if row else None


# ── Activity log ─────────────────────────────────────────────────────────────

def log_activity(user_id: int | None, action: str, detail: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO activity_log (user_id, action, detail) VALUES (?, ?, ?)",
            (user_id, action, detail),
        )
        c.commit()


# ── Admin analytics ───────────────────────────────────────────────────────────

def admin_overview() -> dict:
    with _conn() as c:
        users = c.execute(
            "SELECT COUNT(*) FROM users WHERE password_hash IS NOT NULL").fetchone()[0]
        convs = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        msgs = c.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
        user_msgs = c.execute(
            "SELECT COUNT(*) FROM chat_history WHERE role='user'").fetchone()[0]
        files = c.execute(
            "SELECT COUNT(*) FROM uploaded_files WHERE direction='output'").fetchone()[0]
        active_today = c.execute(
            "SELECT COUNT(DISTINCT user_id) FROM activity_log "
            "WHERE created_at >= datetime('now','-1 day')").fetchone()[0]
    return {
        "users": users, "conversations": convs, "messages": msgs,
        "user_messages": user_msgs, "generated_files": files, "active_today": active_today,
    }


def admin_user_stats() -> list[dict]:
    with _conn() as c:
        rows = c.execute("""
            SELECT u.id, u.username, u.full_name, u.role, u.active, u.created_at,
                   (SELECT COUNT(*) FROM conversations cv WHERE cv.user_id = u.id) AS conversations,
                   (SELECT COUNT(*) FROM chat_history ch
                      WHERE ch.user_id = u.id AND ch.role='user') AS messages,
                   (SELECT MAX(created_at) FROM activity_log al WHERE al.user_id = u.id) AS last_active
            FROM users u
            WHERE u.password_hash IS NOT NULL
            ORDER BY messages DESC, u.id
        """).fetchall()
    return [dict(r) for r in rows]


def messages_per_day(days: int = 14) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT date(created_at) AS day, COUNT(*) AS count FROM chat_history "
            "WHERE role='user' AND created_at >= date('now', ?) "
            "GROUP BY day ORDER BY day",
            (f"-{int(days)} days",),
        ).fetchall()
    return [dict(r) for r in rows]


def admin_conversations(user_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("""
            SELECT cv.id, cv.title, cv.created_at, cv.updated_at,
                   (SELECT COUNT(*) FROM chat_history ch WHERE ch.conversation_id = cv.id) AS messages
            FROM conversations cv WHERE cv.user_id = ? ORDER BY cv.updated_at DESC
        """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


def activity_log_list(limit: int = 200, user_id: int | None = None) -> list[dict]:
    with _conn() as c:
        if user_id:
            rows = c.execute(
                "SELECT al.id, al.user_id, u.username, u.full_name, al.action, al.detail, al.created_at "
                "FROM activity_log al LEFT JOIN users u ON u.id = al.user_id "
                "WHERE al.user_id = ? ORDER BY al.id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT al.id, al.user_id, u.username, u.full_name, al.action, al.detail, al.created_at "
                "FROM activity_log al LEFT JOIN users u ON u.id = al.user_id "
                "ORDER BY al.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]
