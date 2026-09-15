from __future__ import annotations

import re
from html import unescape

_OG_TITLE = re.compile(r'property="og:title"\s+content="([^"]*)"', re.I)
_OG_DESC = re.compile(r'property="og:description"\s+content="([^"]*)"', re.I)

_BAD = (
    "everything you should know",
    "how to",
    "explained",
    "what is a",
    "what are",
    "documentary",
    "recipe",
    "facts about",
    "tedx",
    "vsauce",
    "crash course",
    "wikipedia",
    "tutorial",
)


def parse_og_meta(html: str) -> tuple[str, str]:
    """Return (track_name, artists) from a Spotify open.spotify.com HTML page."""
    title_m = _OG_TITLE.search(html)
    desc_m = _OG_DESC.search(html)
    name = unescape(title_m.group(1)).strip() if title_m else ""
    desc = unescape(desc_m.group(1)).strip() if desc_m else ""
    artists = ""
    parts = [p.strip() for p in desc.split("·") if p.strip()]
    if parts:
        artists = parts[0]
        if not name and len(parts) >= 2:
            name = parts[1]
    if " by " in name and not artists:
        name, artists = name.rsplit(" by ", 1)
    return name.strip() or "Unknown", artists.strip() or "Unknown"


def _primary_artist(artist: str) -> str:
    artist = (artist or "").strip()
    if not artist or artist.lower() == "unknown":
        return ""
    return artist.split(",")[0].strip()


def search_query(artist: str, name: str) -> str:
    name = (name or "").strip()
    primary = _primary_artist(artist)
    if primary:
        return f"{primary} {name}"
    return name


def search_queries(artist: str, name: str) -> list[str]:
    """Comma-separated Spotify credits break YouTube search; try a few clean queries."""
    name = (name or "").strip()
    primary = _primary_artist(artist)
    cleaned = " ".join(
        part.strip()
        for part in (artist or "").replace("&", ",").split(",")
        if part.strip() and part.strip().lower() != "unknown"
    )
    queries: list[str] = []
    if primary:
        queries.extend(
            [
                f"{primary} {name}",
                f"{primary} - {name}",
                f"{primary} {name} audio",
            ]
        )
    if cleaned and cleaned != primary:
        queries.append(f"{cleaned} {name}")
    if name:
        queries.append(f"{name} {primary} audio" if primary else f"{name} official audio")
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        key = q.lower()
        if key in seen or not q.strip():
            continue
        seen.add(key)
        out.append(q)
    return out


def score_video(video_title: str, artist: str, name: str) -> int:
    title = (video_title or "").lower()
    track = (name or "").lower().strip()
    who = (artist or "").lower().strip()
    primary = who.split(",")[0].strip()
    score = 0
    if track and track in title:
        score += 6
    if primary and primary not in {"unknown", ""} and primary in title:
        score += 6
    elif who and who not in {"unknown", ""} and who in title:
        score += 6
    if "official audio" in title:
        score += 3
    elif "official" in title:
        score += 2
    if "lyrics" in title:
        score += 2
    if any(bad in title for bad in _BAD):
        score -= 12
    if "slowed" in title or "nightcore" in title or "1 hour" in title or "1hr" in title:
        score -= 2
    return score


def pick_best_entry(entries: list[dict], artist: str, name: str) -> dict | None:
    ranked: list[tuple[int, dict]] = []
    for entry in entries:
        title = entry.get("title") or ""
        ranked.append((score_video(title, artist, name), entry))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return None
    best_score, best = ranked[0]
    who = (artist or "").lower().strip()
    primary = who.split(",")[0].strip()
    has_artist = primary not in {"", "unknown"}
    if has_artist and best_score < 8:
        return None
    if best_score < 5:
        return None
    return best
