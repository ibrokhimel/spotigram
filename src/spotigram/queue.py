from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class JobView:
    id: str
    telegram_id: int
    status: str
    created_at: str


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def can_enqueue(
    jobs: list[JobView],
    user_id: int,
    *,
    max_running_per_user: int = 1,
    max_queued_per_user: int = 2,
) -> tuple[bool, str]:
    """Return (ok, reason). A user may have 1 running + 2 queued (3 total)."""
    mine = [j for j in jobs if j.telegram_id == user_id and j.status in {"queued", "running"}]
    running = sum(1 for j in mine if j.status == "running")
    queued = sum(1 for j in mine if j.status == "queued")
    if running >= max_running_per_user and queued >= max_queued_per_user:
        return False, "Finish or /cancel one first."
    if running + queued >= max_running_per_user + max_queued_per_user:
        return False, "Finish or /cancel one first."
    return True, ""


def pick_next(jobs: list[JobView], max_running: int = 2) -> JobView | None:
    """Oldest queued job whose user is not already running, if a global slot is free."""
    running = [j for j in jobs if j.status == "running"]
    if len(running) >= max_running:
        return None
    running_users = {j.telegram_id for j in running}
    queued = sorted(
        (j for j in jobs if j.status == "queued"),
        key=lambda j: (_parse_ts(j.created_at), j.id),
    )
    for job in queued:
        if job.telegram_id not in running_users:
            return job
    return None


def queue_position(jobs: list[JobView], job_id: str) -> int | None:
    """1-based FIFO index among queued jobs."""
    queued = sorted(
        (j for j in jobs if j.status == "queued"),
        key=lambda j: (_parse_ts(j.created_at), j.id),
    )
    for i, job in enumerate(queued, start=1):
        if job.id == job_id:
            return i
    return None
