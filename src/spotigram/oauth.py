from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def parse_callback_url(text: str) -> tuple[str, str] | None:
    """Extract (code, state) from a pasted Spotify redirect URL."""
    if not text:
        return None
    raw = text.strip()
    if "code=" not in raw:
        return None
    if "://" not in raw and raw.startswith("/"):
        raw = "http://127.0.0.1" + raw
    elif "://" not in raw:
        raw = "http://127.0.0.1/callback?" + raw.lstrip("?")
    parsed = urlparse(raw)
    query = parse_qs(parsed.query)
    code = (query.get("code") or [None])[0]
    state = (query.get("state") or [None])[0]
    if not code or not state:
        return None
    return code, state
