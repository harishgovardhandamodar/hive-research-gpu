from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


class UserManager:
    def __init__(self, db_dir: str | Path) -> None:
        self._db_dir = Path(db_dir)
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._db_dir / "users.db"
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_login TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
        conn.commit()
        conn.close()

    def _hash_password(self, password: str) -> str:
        salt = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
        return salt + ":" + hashlib.sha256((salt + password).encode()).hexdigest()

    def _verify_password(self, password: str, password_hash: str) -> bool:
        if ":" not in password_hash:
            return False
        salt, hsh = password_hash.split(":", 1)
        return hsh == hashlib.sha256((salt + password).encode()).hexdigest()

    def _generate_token(self) -> str:
        return secrets.token_hex(32)

    def register(self, username: str, password: str) -> dict[str, Any]:
        if len(username) < 2:
            return {"error": "Username must be at least 2 characters"}
        if len(password) < 4:
            return {"error": "Password must be at least 4 characters"}
        with self._lock:
            conn = self._conn()
            try:
                existing = conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()
                if existing:
                    return {"error": "Username already exists"}
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, self._hash_password(password)),
                )
                conn.commit()
                user_id = conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()["id"]
                token = self._create_session(conn, user_id)
                return {"status": "ok", "token": token, "user": {"id": user_id, "username": username}}
            finally:
                conn.close()

    def login(self, username: str, password: str) -> dict[str, Any]:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT id, username, password_hash FROM users WHERE username = ?",
                    (username,),
                ).fetchone()
                if not row:
                    return {"error": "Invalid username or password"}
                if not self._verify_password(password, row["password_hash"]):
                    return {"error": "Invalid username or password"}
                conn.execute(
                    "UPDATE users SET last_login = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), row["id"]),
                )
                conn.commit()
                token = self._create_session(conn, row["id"])
                return {"status": "ok", "token": token, "user": {"id": row["id"], "username": row["username"]}}
            finally:
                conn.close()

    def logout(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)
            conn = self._conn()
            try:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
            finally:
                conn.close()

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            if token in self._sessions:
                sess = self._sessions[token]
                if sess["expires_at"] > time.time():
                    return sess["user"]
                self._sessions.pop(token, None)
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT s.token, s.user_id, s.expires_at, u.username "
                    "FROM sessions s JOIN users u ON s.user_id = u.id "
                    "WHERE s.token = ?",
                    (token,),
                ).fetchone()
                if not row:
                    return None
                expires = datetime.fromisoformat(row["expires_at"]).timestamp()
                if expires < time.time():
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    conn.commit()
                    return None
                user = {"id": row["user_id"], "username": row["username"]}
                self._sessions[token] = {"user": user, "expires_at": expires}
                return user
            finally:
                conn.close()

    def _create_session(self, conn: sqlite3.Connection, user_id: int) -> str:
        token = self._generate_token()
        expires = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, datetime('now', '+7 days'))",
            (token, user_id),
        )
        conn.commit()
        expires_ts = time.time() + 7 * 86400
        self._sessions[token] = {
            "user": {"id": user_id},
            "expires_at": expires_ts,
        }
        return token

    def get_all_users(self) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, username, created_at, last_login FROM users ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
