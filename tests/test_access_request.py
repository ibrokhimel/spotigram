import pytest

from spotigram.access import HARDCODED_ADMIN_ID, approved_text
from spotigram.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "t.db")
    await database.connect()
    await database.seed_admins([HARDCODED_ADMIN_ID])
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_admin_is_seeded(db: Database):
    assert await db.is_admin(HARDCODED_ADMIN_ID)
    assert await db.is_approved(HARDCODED_ADMIN_ID)


@pytest.mark.asyncio
async def test_approve_flow(db: Database):
    await db.upsert_pending_request(999, "alice", "Alice", HARDCODED_ADMIN_ID, 1)
    req = await db.get_request(999)
    assert req is not None
    assert req.status == "pending"
    await db.approve_user(999, "alice", "Alice")
    assert await db.is_approved(999)
    req2 = await db.get_request(999)
    assert req2 is not None
    assert req2.status == "approved"
    assert approved_text("alice", "Alice", 999) == "approved @alice"


@pytest.mark.asyncio
async def test_deny_and_cannot_demote_admin(db: Database):
    await db.deny_user(888)
    assert not await db.is_approved(888)
    user = await db.get_user(888)
    assert user is not None
    assert user.status == "denied"
    await db.remove_user(HARDCODED_ADMIN_ID)
    assert await db.is_admin(HARDCODED_ADMIN_ID)
    assert await db.is_approved(HARDCODED_ADMIN_ID)
