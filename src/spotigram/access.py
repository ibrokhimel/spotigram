from __future__ import annotations

HARDCODED_ADMIN_ID = 1406109190
ADMIN_HANDLE = "@ibrokhimel"


def mention(username: str | None, first_name: str | None, telegram_id: int) -> str:
    if username:
        return f"@{username.lstrip('@')}"
    if first_name:
        return first_name
    return str(telegram_id)


def approved_text(username: str | None, first_name: str | None, telegram_id: int) -> str:
    return f"approved {mention(username, first_name, telegram_id)}"


def denied_text(username: str | None, first_name: str | None, telegram_id: int) -> str:
    return f"denied {mention(username, first_name, telegram_id)}"


def private_start_text(handle: str = ADMIN_HANDLE) -> str:
    return f"This bot is private. Ask {handle} to approve you, or wait here."


def pending_start_text(handle: str = ADMIN_HANDLE) -> str:
    return f"Still waiting. Ask {handle} or wait."


def denied_start_text(handle: str = ADMIN_HANDLE) -> str:
    return f"Not approved. Ask {handle}."
