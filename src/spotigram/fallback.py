from __future__ import annotations

YOUTUBE = ("youtube-music", "youtube")
SOUNDCLOUD = ("soundcloud",)

VALID_SOURCES = frozenset({"youtube", "soundcloud", "auto"})


def provider_attempts(source: str) -> list[tuple[str, ...]]:
    """Ordered spotDL --audio groups. First miss → second group. Never Spotify streams."""
    src = (source or "auto").lower()
    if src not in VALID_SOURCES:
        src = "auto"
    if src == "soundcloud":
        return [SOUNDCLOUD, YOUTUBE]
    return [YOUTUBE, SOUNDCLOUD]


def other_source_label(attempt_index: int, source: str) -> str:
    attempts = provider_attempts(source)
    if attempt_index >= len(attempts):
        return "none"
    group = attempts[attempt_index]
    if group == SOUNDCLOUD:
        return "SoundCloud"
    return "YouTube"
