from spotigram.urls import parse_spotify


def test_track_url():
    ref = parse_spotify("https://open.spotify.com/track/2KUmkYMFnsiVPCOGx1gefj")
    assert ref is not None
    assert ref.kind == "track"
    assert ref.id == "2KUmkYMFnsiVPCOGx1gefj"


def test_playlist_with_si():
    ref = parse_spotify(
        "check this https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc"
    )
    assert ref is not None
    assert ref.kind == "playlist"
    assert ref.id == "37i9dQZF1DXcBWIGoYBM5M"


def test_intl_album():
    ref = parse_spotify("https://open.spotify.com/intl-de/album/4yP0hdKOZPNshxUOjY0cZj")
    assert ref is not None
    assert ref.kind == "album"
    assert ref.id == "4yP0hdKOZPNshxUOjY0cZj"


def test_spotify_uri():
    ref = parse_spotify("spotify:artist:1Xyo4u8uXC1ZmMpatF05PJ")
    assert ref is not None
    assert ref.kind == "artist"
    assert ref.url.endswith("/artist/1Xyo4u8uXC1ZmMpatF05PJ")


def test_not_spotify():
    assert parse_spotify("https://youtube.com/watch?v=abc") is None
    assert parse_spotify("hello") is None
    assert parse_spotify("") is None


def test_collection_flag():
    assert parse_spotify("https://open.spotify.com/track/abc123abc12").is_collection is False
    assert parse_spotify("https://open.spotify.com/playlist/abc123abc12").is_collection is True
