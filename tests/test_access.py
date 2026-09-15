from spotigram.access import (
    HARDCODED_ADMIN_ID,
    approved_text,
    denied_text,
    mention,
    pending_start_text,
    private_start_text,
)


def test_mention_prefers_username():
    assert mention("alice", "Alice", 1) == "@alice"
    assert mention("@alice", "Alice", 1) == "@alice"


def test_mention_falls_back():
    assert mention(None, "Alice", 999) == "Alice"
    assert mention(None, None, 999) == "999"


def test_approved_copy():
    assert approved_text("alice", "Alice", 1) == "approved @alice"
    assert approved_text(None, "Bob", 2) == "approved Bob"


def test_denied_copy():
    assert denied_text("alice", "Alice", 1) == "denied @alice"


def test_start_copy_mentions_admin():
    assert "@ibrokhimel" in private_start_text()
    assert "@ibrokhimel" in pending_start_text()


def test_hardcoded_admin():
    assert HARDCODED_ADMIN_ID == 1406109190
