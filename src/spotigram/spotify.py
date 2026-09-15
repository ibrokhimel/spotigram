from __future__ import annotations

from typing import Any

import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth

from spotigram.models import CollectionMeta, TrackMeta
from spotigram.urls import SpotifyRef

SCOPES = " ".join(
    [
        "user-library-read",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-read-private",
    ]
)


def _artists(item: dict[str, Any]) -> str:
    return ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))


def _cover(images: list[dict] | None) -> str | None:
    if not images:
        return None
    return images[0].get("url")


def track_from_api(item: dict[str, Any]) -> TrackMeta | None:
    track = item.get("track") if "track" in item else item
    if not track or track.get("is_local") or not track.get("id"):
        return None
    album = track.get("album") or {}
    tid = track["id"]
    return TrackMeta(
        id=tid,
        name=track.get("name") or "Unknown",
        artists=_artists(track) or "Unknown",
        album=album.get("name") or "",
        duration_ms=int(track.get("duration_ms") or 0),
        cover_url=_cover(album.get("images")),
        url=f"https://open.spotify.com/track/{tid}",
    )


def _ensure_spotdl_client() -> None:
    from spotdl.utils.spotify import SpotifyClient, SpotifyError

    try:
        SpotifyClient.init(
            client_id="disabled",
            client_secret="disabled",
            use_official_api=False,
            no_cache=True,
            headless=True,
        )
    except SpotifyError:
        pass


def _song_to_track(song: Any) -> TrackMeta | None:
    sid = getattr(song, "song_id", None) or ""
    if not sid and getattr(song, "url", None):
        sid = str(song.url).rstrip("/").split("/")[-1]
    if not sid:
        return None
    artists = song.artists if isinstance(song.artists, str) else ", ".join(song.artists or [])
    duration_ms = int(float(song.duration or 0) * 1000)
    if duration_ms < 1000 and song.duration and song.duration > 1000:
        duration_ms = int(song.duration)
    return TrackMeta(
        id=sid,
        name=song.name or "Unknown",
        artists=artists or "Unknown",
        album=song.album_name or "",
        duration_ms=duration_ms,
        cover_url=song.cover_url,
        url=song.url or f"https://open.spotify.com/track/{sid}",
    )


class SpotifyService:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        # Official Web API now requires Premium on the app owner (403).
        # Public catalog lookups always go through spotDL / SpotipyFree.
        self._public: spotipy.Spotify | None = None

    def _client(self, user_token: str | None = None) -> spotipy.Spotify:
        if user_token:
            return spotipy.Spotify(auth=user_token)
        if self._public is None:
            raise RuntimeError(
                "Spotify app credentials are not set. Public links still work via spotDL."
            )
        return self._public

    def auth_manager(self, cache_path: str | None = None) -> SpotifyOAuth:
        return SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=SCOPES,
            open_browser=False,
            cache_handler=MemoryCacheHandler(),
        )

    def authorize_url(self, state: str) -> str:
        return self.auth_manager().get_authorize_url(state=state)

    def exchange_code(self, code: str) -> dict:
        return self.auth_manager().get_access_token(code, as_dict=True, check_cache=False)

    def me(self, user_token: str) -> dict:
        return self._client(user_token).me()

    def fetch(self, ref: SpotifyRef, user_token: str | None = None, cap: int = 200) -> CollectionMeta:
        last: Exception | None = None
        if ref.kind == "track":
            try:
                return self._fetch_oembed_track(ref)
            except Exception as exc:
                last = exc
        try:
            col = self._fetch_spotdl(ref, cap)
            if col.tracks:
                return col
        except Exception as exc:
            last = exc
        if user_token:
            try:
                return self._fetch_official(ref, user_token, cap)
            except spotipy.SpotifyException as exc:
                if getattr(exc, "http_status", None) == 403:
                    if last:
                        raise last from exc
                    return self._fetch_spotdl(ref, cap)
                if last:
                    raise last from exc
                raise
            except Exception as exc:
                if last:
                    raise last from exc
                raise
        if last:
            raise last
        return CollectionMeta(ref.kind, ref.id, ref.id, [])

    def _fetch_official(
        self, ref: SpotifyRef, user_token: str | None, cap: int
    ) -> CollectionMeta:
        sp = self._client(user_token)
        if ref.kind == "track":
            raw = sp.track(ref.id)
            track = track_from_api(raw)
            tracks = [track] if track else []
            title = tracks[0].name if tracks else ref.id
            return CollectionMeta(ref.kind, ref.id, title, tracks)
        if ref.kind == "album":
            album = sp.album(ref.id)
            tracks = self._paginate_album(sp, ref.id, cap)
            return CollectionMeta(ref.kind, ref.id, album.get("name") or "Album", tracks)
        if ref.kind == "playlist":
            playlist = sp.playlist(ref.id, fields="name,tracks")
            tracks = self._paginate_playlist(sp, ref.id, cap)
            return CollectionMeta(ref.kind, ref.id, playlist.get("name") or "Playlist", tracks)
        if ref.kind == "artist":
            artist = sp.artist(ref.id)
            tracks = self._artist_tracks(sp, ref.id, cap)
            return CollectionMeta(ref.kind, ref.id, artist.get("name") or "Artist", tracks)
        raise ValueError(f"unsupported kind {ref.kind}")

    def _fetch_oembed_track(self, ref: SpotifyRef) -> CollectionMeta:
        import json
        import urllib.parse
        import urllib.request

        from spotigram.match import parse_og_meta

        headers = {"User-Agent": "Mozilla/5.0 (compatible; Spotigram/0.1)"}
        name, artists, cover = "Unknown", "Unknown", None
        try:
            page_req = urllib.request.Request(ref.url, headers=headers)
            with urllib.request.urlopen(page_req, timeout=12) as resp:
                html = resp.read().decode("utf-8", "replace")
            name, artists = parse_og_meta(html)
        except Exception:
            pass
        oembed = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(ref.url, safe="")
        try:
            req = urllib.request.Request(oembed, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cover = data.get("thumbnail_url")
            if name in {"", "Unknown"} and data.get("title"):
                name = str(data["title"]).strip()
            if artists in {"", "Unknown"} and " by " in name:
                name, artists = name.rsplit(" by ", 1)
        except Exception:
            pass
        return CollectionMeta(
            ref.kind,
            ref.id,
            name.strip(),
            [
                TrackMeta(
                    id=ref.id,
                    name=name.strip() or "Unknown",
                    artists=artists.strip() or "Unknown",
                    album="",
                    duration_ms=0,
                    cover_url=cover,
                    url=ref.url,
                )
            ],
        )

    def _fetch_spotdl(self, ref: SpotifyRef, cap: int) -> CollectionMeta:
        from spotdl.utils.search import get_simple_songs

        _ensure_spotdl_client()
        songs = get_simple_songs([ref.url])
        tracks: list[TrackMeta] = []
        title = ref.id
        for song in songs[:cap]:
            meta = _song_to_track(song)
            if meta:
                tracks.append(meta)
            if getattr(song, "list_name", None):
                title = song.list_name
        if ref.kind == "track" and tracks:
            title = tracks[0].name
        return CollectionMeta(ref.kind, ref.id, title or ref.id, tracks)

    def liked_songs(self, user_token: str, cap: int = 200) -> CollectionMeta:
        sp = self._client(user_token)
        tracks: list[TrackMeta] = []
        results = sp.current_user_saved_tracks(limit=50)
        while results and len(tracks) < cap:
            for item in results.get("items") or []:
                meta = track_from_api(item)
                if meta:
                    tracks.append(meta)
                if len(tracks) >= cap:
                    break
            if results.get("next"):
                results = sp.next(results)
            else:
                break
        return CollectionMeta("liked", "liked", "Liked Songs", tracks)

    def user_playlists(self, user_token: str) -> list[tuple[str, str, int]]:
        sp = self._client(user_token)
        out: list[tuple[str, str, int]] = []
        results = sp.current_user_playlists(limit=50)
        while results:
            for item in results.get("items") or []:
                pid = item.get("id")
                name = item.get("name") or "Playlist"
                total = (item.get("tracks") or {}).get("total") or 0
                if pid:
                    out.append((pid, name, int(total)))
            if results.get("next"):
                results = sp.next(results)
            else:
                break
        return out

    def _paginate_playlist(self, sp: spotipy.Spotify, playlist_id: str, cap: int) -> list[TrackMeta]:
        tracks: list[TrackMeta] = []
        results = sp.playlist_items(playlist_id, additional_types=["track"], limit=100)
        while results and len(tracks) < cap:
            for item in results.get("items") or []:
                meta = track_from_api(item)
                if meta:
                    tracks.append(meta)
                if len(tracks) >= cap:
                    break
            if results.get("next"):
                results = sp.next(results)
            else:
                break
        return tracks

    def _paginate_album(self, sp: spotipy.Spotify, album_id: str, cap: int) -> list[TrackMeta]:
        album = sp.album(album_id)
        cover = _cover(album.get("images"))
        album_name = album.get("name") or ""
        tracks: list[TrackMeta] = []
        results = sp.album_tracks(album_id, limit=50)
        while results and len(tracks) < cap:
            for item in results.get("items") or []:
                if not item.get("id"):
                    continue
                tracks.append(
                    TrackMeta(
                        id=item["id"],
                        name=item.get("name") or "Unknown",
                        artists=_artists(item) or "Unknown",
                        album=album_name,
                        duration_ms=int(item.get("duration_ms") or 0),
                        cover_url=cover,
                        url=f"https://open.spotify.com/track/{item['id']}",
                    )
                )
                if len(tracks) >= cap:
                    break
            if results.get("next"):
                results = sp.next(results)
            else:
                break
        return tracks

    def _artist_tracks(self, sp: spotipy.Spotify, artist_id: str, cap: int) -> list[TrackMeta]:
        tracks: list[TrackMeta] = []
        seen_ids: set[str] = set()
        albums = sp.artist_albums(artist_id, album_type="album,single", limit=50)
        album_ids: list[str] = []
        while albums:
            for item in albums.get("items") or []:
                if item.get("id"):
                    album_ids.append(item["id"])
            if albums.get("next"):
                albums = sp.next(albums)
            else:
                break
        for album_id in album_ids:
            for track in self._paginate_album(sp, album_id, cap):
                if track.id in seen_ids:
                    continue
                seen_ids.add(track.id)
                tracks.append(track)
                if len(tracks) >= cap:
                    return tracks
        return tracks
