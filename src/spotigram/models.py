from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrackMeta:
    id: str
    name: str
    artists: str
    album: str
    duration_ms: int
    cover_url: str | None
    url: str

    @property
    def duration_s(self) -> int:
        return max(0, self.duration_ms // 1000)

    @property
    def caption_line(self) -> str:
        mins, secs = divmod(self.duration_s, 60)
        return f"{self.artists} — {self.name}\n{self.album} · {mins}:{secs:02d}"


@dataclass
class CollectionMeta:
    ref_kind: str
    ref_id: str
    title: str
    tracks: list[TrackMeta] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/{self.ref_kind}/{self.ref_id}"


@dataclass
class Wizard:
    token: str
    telegram_id: int
    chat_id: int
    kind: str
    query: str
    title: str
    tracks: list[TrackMeta]
    format: str | None = None
    source: str | None = None
    delivery: str | None = None
    warned: bool = False
