from spotigram.queue import JobView, can_enqueue, pick_next, queue_position


def _job(jid: str, user: int, status: str, ts: str) -> JobView:
    return JobView(id=jid, telegram_id=user, status=status, created_at=ts)


def test_pick_next_respects_global_cap():
    jobs = [
        _job("a", 1, "running", "2026-01-01T00:00:00+00:00"),
        _job("b", 2, "running", "2026-01-01T00:00:01+00:00"),
        _job("c", 3, "queued", "2026-01-01T00:00:02+00:00"),
    ]
    assert pick_next(jobs, max_running=2) is None


def test_fifo_and_user_not_already_running():
    jobs = [
        _job("a", 1, "running", "2026-01-01T00:00:00+00:00"),
        _job("b", 1, "queued", "2026-01-01T00:00:01+00:00"),
        _job("c", 2, "queued", "2026-01-01T00:00:02+00:00"),
    ]
    nxt = pick_next(jobs, max_running=2)
    assert nxt is not None
    assert nxt.id == "c"


def test_oldest_queued_wins():
    jobs = [
        _job("b", 2, "queued", "2026-01-01T00:00:02+00:00"),
        _job("a", 1, "queued", "2026-01-01T00:00:01+00:00"),
    ]
    nxt = pick_next(jobs, max_running=2)
    assert nxt is not None
    assert nxt.id == "a"


def test_per_user_cap():
    jobs = [
        _job("a", 1, "running", "2026-01-01T00:00:00+00:00"),
        _job("b", 1, "queued", "2026-01-01T00:00:01+00:00"),
        _job("c", 1, "queued", "2026-01-01T00:00:02+00:00"),
    ]
    ok, reason = can_enqueue(jobs, 1)
    assert ok is False
    assert "cancel" in reason.lower()
    ok2, _ = can_enqueue(jobs, 2)
    assert ok2 is True


def test_queue_position():
    jobs = [
        _job("a", 1, "queued", "2026-01-01T00:00:01+00:00"),
        _job("b", 2, "queued", "2026-01-01T00:00:02+00:00"),
        _job("c", 3, "running", "2026-01-01T00:00:00+00:00"),
    ]
    assert queue_position(jobs, "b") == 2
    assert queue_position(jobs, "a") == 1
    assert queue_position(jobs, "c") is None
