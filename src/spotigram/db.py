from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from spotigram.access import HARDCODED_ADMIN_ID
from spotigram.queue import JobView, can_enqueue, pick_next, queue_position

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_requests (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    status TEXT NOT NULL,
    admin_chat_id INTEGER,
    admin_message_id INTEGER,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    telegram_id INTEGER PRIMARY KEY,
    format TEXT,
    source TEXT,
    delivery TEXT
);
CREATE TABLE IF NOT EXISTS oauth (
    telegram_id INTEGER PRIMARY KEY,
    display_name TEXT,
    access_token TEXT,
    refresh_token TEXT,
    expires_at INTEGER
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    telegram_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    query TEXT NOT NULL,
    format TEXT,
    source TEXT,
    delivery TEXT,
    status TEXT NOT NULL,
    queue_position INTEGER,
    total INTEGER DEFAULT 0,
    done_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    fallback_count INTEGER DEFAULT 0,
    metadata_only_count INTEGER DEFAULT 0,
    chat_id INTEGER,
    status_message_id INTEGER,
    error TEXT,
    title TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    telegram_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UserRow:
    telegram_id: int
    username: str | None
    first_name: str | None
    is_admin: bool
    status: str


@dataclass
class RequestRow:
    telegram_id: int
    username: str | None
    first_name: str | None
    status: str
    admin_chat_id: int | None
    admin_message_id: int | None


@dataclass
class JobRow:
    id: str
    telegram_id: int
    kind: str
    query: str
    format: str | None
    source: str | None
    delivery: str | None
    status: str
    total: int
    done_count: int
    failed_count: int
    fallback_count: int
    metadata_only_count: int
    chat_id: int | None
    status_message_id: int | None
    error: str | None
    title: str | None
    created_at: str
    finished_at: str | None


def _job_from_row(row: aiosqlite.Row) -> JobRow:
    return JobRow(
        id=row["id"],
        telegram_id=row["telegram_id"],
        kind=row["kind"],
        query=row["query"],
        format=row["format"],
        source=row["source"],
        delivery=row["delivery"],
        status=row["status"],
        total=row["total"] or 0,
        done_count=row["done_count"] or 0,
        failed_count=row["failed_count"] or 0,
        fallback_count=row["fallback_count"] or 0,
        metadata_only_count=row["metadata_only_count"] or 0,
        chat_id=row["chat_id"],
        status_message_id=row["status_message_id"],
        error=row["error"],
        title=row["title"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
    )


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None
        return self._conn

    async def seed_admins(self, admin_ids: list[int]) -> None:
        for admin_id in admin_ids:
            await self.conn.execute(
                """
                INSERT INTO users (telegram_id, is_admin, status, created_at)
                VALUES (?, 1, 'approved', ?)
                ON CONFLICT(telegram_id) DO UPDATE SET is_admin=1, status='approved'
                """,
                (admin_id, _now()),
            )
        await self.conn.execute(
            """
            UPDATE users SET is_admin=1, status='approved' WHERE telegram_id=?
            """,
            (HARDCODED_ADMIN_ID,),
        )
        await self.conn.commit()

    async def get_user(self, telegram_id: int) -> UserRow | None:
        cur = await self.conn.execute(
            "SELECT * FROM users WHERE telegram_id=?", (telegram_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return UserRow(
            telegram_id=row["telegram_id"],
            username=row["username"],
            first_name=row["first_name"],
            is_admin=bool(row["is_admin"]),
            status=row["status"],
        )

    async def is_approved(self, telegram_id: int) -> bool:
        if telegram_id == HARDCODED_ADMIN_ID:
            return True
        user = await self.get_user(telegram_id)
        return bool(user and user.status == "approved")

    async def is_admin(self, telegram_id: int) -> bool:
        if telegram_id == HARDCODED_ADMIN_ID:
            return True
        user = await self.get_user(telegram_id)
        return bool(user and user.is_admin)

    async def get_request(self, telegram_id: int) -> RequestRow | None:
        cur = await self.conn.execute(
            "SELECT * FROM access_requests WHERE telegram_id=?", (telegram_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return RequestRow(
            telegram_id=row["telegram_id"],
            username=row["username"],
            first_name=row["first_name"],
            status=row["status"],
            admin_chat_id=row["admin_chat_id"],
            admin_message_id=row["admin_message_id"],
        )

    async def upsert_pending_request(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        admin_chat_id: int,
        admin_message_id: int,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO access_requests (
                telegram_id, username, first_name, status,
                admin_chat_id, admin_message_id, created_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                status='pending',
                admin_chat_id=excluded.admin_chat_id,
                admin_message_id=excluded.admin_message_id
            """,
            (telegram_id, username, first_name, admin_chat_id, admin_message_id, _now()),
        )
        await self.conn.commit()

    async def approve_user(
        self, telegram_id: int, username: str | None, first_name: str | None
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, is_admin, status, created_at)
            VALUES (?, ?, ?, 0, 'approved', ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                status='approved'
            """,
            (telegram_id, username, first_name, _now()),
        )
        await self.conn.execute(
            """
            UPDATE access_requests SET status='approved', resolved_at=? WHERE telegram_id=?
            """,
            (_now(), telegram_id),
        )
        await self.conn.commit()

    async def deny_user(self, telegram_id: int) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (telegram_id, is_admin, status, created_at)
            VALUES (?, 0, 'denied', ?)
            ON CONFLICT(telegram_id) DO UPDATE SET status='denied', is_admin=0
            """,
            (telegram_id, _now()),
        )
        await self.conn.execute(
            """
            UPDATE access_requests SET status='denied', resolved_at=? WHERE telegram_id=?
            """,
            (_now(), telegram_id),
        )
        await self.conn.commit()

    async def list_users(self) -> list[UserRow]:
        cur = await self.conn.execute("SELECT * FROM users ORDER BY created_at")
        rows = await cur.fetchall()
        return [
            UserRow(
                telegram_id=r["telegram_id"],
                username=r["username"],
                first_name=r["first_name"],
                is_admin=bool(r["is_admin"]),
                status=r["status"],
            )
            for r in rows
        ]

    async def list_pending_requests(self) -> list[RequestRow]:
        cur = await self.conn.execute(
            "SELECT * FROM access_requests WHERE status='pending'"
        )
        rows = await cur.fetchall()
        return [
            RequestRow(
                telegram_id=r["telegram_id"],
                username=r["username"],
                first_name=r["first_name"],
                status=r["status"],
                admin_chat_id=r["admin_chat_id"],
                admin_message_id=r["admin_message_id"],
            )
            for r in rows
        ]

    async def add_user(self, telegram_id: int) -> None:
        await self.approve_user(telegram_id, None, None)

    async def remove_user(self, telegram_id: int) -> None:
        if telegram_id == HARDCODED_ADMIN_ID:
            return
        await self.deny_user(telegram_id)

    async def get_settings(self, telegram_id: int) -> dict[str, str | None]:
        cur = await self.conn.execute(
            "SELECT format, source, delivery FROM settings WHERE telegram_id=?",
            (telegram_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {"format": None, "source": None, "delivery": None}
        return {
            "format": row["format"],
            "source": row["source"],
            "delivery": row["delivery"],
        }

    async def set_settings(
        self,
        telegram_id: int,
        *,
        format: str | None = None,
        source: str | None = None,
        delivery: str | None = None,
    ) -> None:
        current = await self.get_settings(telegram_id)
        if format is not None:
            current["format"] = format
        if source is not None:
            current["source"] = source
        if delivery is not None:
            current["delivery"] = delivery
        await self.conn.execute(
            """
            INSERT INTO settings (telegram_id, format, source, delivery)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                format=excluded.format,
                source=excluded.source,
                delivery=excluded.delivery
            """,
            (telegram_id, current["format"], current["source"], current["delivery"]),
        )
        await self.conn.commit()

    async def save_oauth(
        self,
        telegram_id: int,
        display_name: str,
        access_token: str,
        refresh_token: str,
        expires_at: int,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO oauth (telegram_id, display_name, access_token, refresh_token, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                display_name=excluded.display_name,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at
            """,
            (telegram_id, display_name, access_token, refresh_token, expires_at),
        )
        await self.conn.commit()

    async def get_oauth(self, telegram_id: int) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM oauth WHERE telegram_id=?", (telegram_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)

    async def delete_oauth(self, telegram_id: int) -> None:
        await self.conn.execute("DELETE FROM oauth WHERE telegram_id=?", (telegram_id,))
        await self.conn.commit()

    async def put_oauth_state(self, state: str, telegram_id: int, expires_at: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO oauth_states (state, telegram_id, expires_at) VALUES (?, ?, ?)",
            (state, telegram_id, expires_at),
        )
        await self.conn.commit()

    async def consume_oauth_state(self, state: str) -> int | None:
        cur = await self.conn.execute(
            "SELECT telegram_id, expires_at FROM oauth_states WHERE state=?", (state,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        await self.conn.execute("DELETE FROM oauth_states WHERE state=?", (state,))
        await self.conn.commit()
        now = int(datetime.now(timezone.utc).timestamp())
        if row["expires_at"] < now:
            return None
        return int(row["telegram_id"])

    def _views(self, rows: list[aiosqlite.Row]) -> list[JobView]:
        return [
            JobView(
                id=r["id"],
                telegram_id=r["telegram_id"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def _active_jobs(self) -> list[JobView]:
        cur = await self.conn.execute(
            "SELECT id, telegram_id, status, created_at FROM jobs WHERE status IN ('queued','running')"
        )
        rows = await cur.fetchall()
        return self._views(rows)

    async def enqueue_allowed(self, telegram_id: int) -> tuple[bool, str]:
        jobs = await self._active_jobs()
        return can_enqueue(jobs, telegram_id)

    async def create_job(
        self,
        telegram_id: int,
        kind: str,
        query: str,
        format: str,
        source: str,
        delivery: str,
        chat_id: int,
        status_message_id: int,
        title: str,
        total: int,
    ) -> JobRow:
        job_id = uuid.uuid4().hex
        created = _now()
        await self.conn.execute(
            """
            INSERT INTO jobs (
                id, telegram_id, kind, query, format, source, delivery,
                status, total, chat_id, status_message_id, title, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                telegram_id,
                kind,
                query,
                format,
                source,
                delivery,
                total,
                chat_id,
                status_message_id,
                title,
                created,
            ),
        )
        await self.conn.commit()
        job = await self.get_job(job_id)
        assert job is not None
        return job

    async def get_job(self, job_id: str) -> JobRow | None:
        cur = await self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = await cur.fetchone()
        return _job_from_row(row) if row else None

    async def user_jobs(self, telegram_id: int) -> list[JobRow]:
        cur = await self.conn.execute(
            "SELECT * FROM jobs WHERE telegram_id=? ORDER BY created_at",
            (telegram_id,),
        )
        return [_job_from_row(r) for r in await cur.fetchall()]

    async def claim_next(self, max_running: int = 2) -> JobRow | None:
        async with self._lock:
            cur = await self.conn.execute(
                "SELECT id, telegram_id, status, created_at FROM jobs WHERE status IN ('queued','running')"
            )
            views = self._views(await cur.fetchall())
            nxt = pick_next(views, max_running=max_running)
            if not nxt:
                return None
            await self.conn.execute(
                "UPDATE jobs SET status='running' WHERE id=? AND status='queued'",
                (nxt.id,),
            )
            await self.conn.commit()
            return await self.get_job(nxt.id)

    async def position_for(self, job_id: str) -> int | None:
        jobs = await self._active_jobs()
        return queue_position(jobs, job_id)

    async def running_count(self) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status='running'"
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def queued_jobs(self) -> list[JobRow]:
        cur = await self.conn.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at"
        )
        return [_job_from_row(r) for r in await cur.fetchall()]

    async def running_jobs(self) -> list[JobRow]:
        cur = await self.conn.execute(
            "SELECT * FROM jobs WHERE status='running' ORDER BY created_at"
        )
        return [_job_from_row(r) for r in await cur.fetchall()]

    async def update_progress(
        self,
        job_id: str,
        *,
        done: int | None = None,
        failed: int | None = None,
        fallback: int | None = None,
        metadata_only: int | None = None,
        status_message_id: int | None = None,
    ) -> None:
        job = await self.get_job(job_id)
        if not job:
            return
        await self.conn.execute(
            """
            UPDATE jobs SET
                done_count=?, failed_count=?, fallback_count=?,
                metadata_only_count=?, status_message_id=COALESCE(?, status_message_id)
            WHERE id=?
            """,
            (
                job.done_count if done is None else done,
                job.failed_count if failed is None else failed,
                job.fallback_count if fallback is None else fallback,
                job.metadata_only_count if metadata_only is None else metadata_only,
                status_message_id,
                job_id,
            ),
        )
        await self.conn.commit()

    async def finish_job(self, job_id: str, status: str, error: str | None = None) -> None:
        await self.conn.execute(
            "UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?",
            (status, error, _now(), job_id),
        )
        await self.conn.commit()

    async def cancel_user_jobs(self, telegram_id: int) -> list[str]:
        cur = await self.conn.execute(
            "SELECT id, status FROM jobs WHERE telegram_id=? AND status IN ('queued','running')",
            (telegram_id,),
        )
        rows = await cur.fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            await self.conn.execute(
                """
                UPDATE jobs SET status='cancelled', finished_at=?
                WHERE telegram_id=? AND status IN ('queued','running')
                """,
                (_now(), telegram_id),
            )
            await self.conn.commit()
        return ids

    async def requeue_running(self) -> None:
        await self.conn.execute(
            "UPDATE jobs SET status='queued' WHERE status='running'"
        )
        await self.conn.commit()
