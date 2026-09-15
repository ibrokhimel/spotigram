from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = frozenset({"track", "album", "playlist", "artist"})

_URL_RE = re.compile(
    r"""
    (?:
        https?://(?:open|play)\.spotify\.com/(?:intl-[a-z]{2}/)?
        |
        spotify:
    )
    (?P<kind>track|album|playlist|artist)
    [:/]
    (?P<id>[A-Za-z0-9]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class SpotifyRef:
    kind: str
    id: str

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/{self.kind}/{self.id}"

    @property
    def uri(self) -> str:
        return f"spotify:{self.kind}:{self.id}"

    @property
    def is_collection(self) -> bool:
        return self.kind in {"album", "playlist", "artist"}


def parse_spotify(text: str) -> SpotifyRef | None:
    """Extract a track/album/playlist/artist ref from a message, or None."""
    if not text:
        return None
    match = _URL_RE.search(text.strip())
    if not match:
        return None
    kind = match.group("kind").lower()
    if kind not in KINDS:
        return None
    return SpotifyRef(kind=kind, id=match.group("id"))
