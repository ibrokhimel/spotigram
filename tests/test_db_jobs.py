import pytest

from spotigram.access import HARDCODED_ADMIN_ID
from spotigram.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "t.db")
    await database.connect()
    await database.seed_admins([HARDCODED_ADMIN_ID])
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_claim_next_fifo_and_user_slot(db: Database):
    await db.approve_user(1, "a", "A")
    await db.approve_user(2, "b", "B")
    j1 = await db.create_job(1, "track", "q1", "mp3", "youtube", "single", 1, 1, "one", 1)
    j2 = await db.create_job(1, "track", "q2", "mp3", "youtube", "single", 1, 1, "two", 1)
    j3 = await db.create_job(2, "track", "q3", "mp3", "youtube", "single", 2, 1, "three", 1)
    first = await db.claim_next(max_running=2)
    assert first is not None and first.id == j1.id
    second = await db.claim_next(max_running=2)
    assert second is not None and second.id == j3.id
    third = await db.claim_next(max_running=2)
    assert third is None
    await db.finish_job(j1.id, "done")
    third = await db.claim_next(max_running=2)
    assert third is not None and third.id == j2.id


@pytest.mark.asyncio
async def test_enqueue_cap(db: Database):
    ok, _ = await db.enqueue_allowed(9)
    assert ok
    await db.create_job(9, "track", "q", "mp3", "auto", "single", 9, 1, "t", 1)
    await db.create_job(9, "track", "q", "mp3", "auto", "single", 9, 1, "t", 1)
    await db.create_job(9, "track", "q", "mp3", "auto", "single", 9, 1, "t", 1)
    ok, reason = await db.enqueue_allowed(9)
    assert ok is False
    assert "cancel" in reason.lower()
