from spotigram.spotify import track_from_api


def test_track_from_api_nested():
    item = {
        "track": {
            "id": "abc",
            "name": "Song",
            "duration_ms": 125000,
            "artists": [{"name": "A"}, {"name": "B"}],
            "album": {
                "name": "LP",
                "images": [{"url": "https://i.scdn.co/cover.jpg"}],
            },
        }
    }
    meta = track_from_api(item)
    assert meta is not None
    assert meta.name == "Song"
    assert meta.artists == "A, B"
    assert meta.album == "LP"
    assert meta.duration_s == 125
    assert meta.url.endswith("/track/abc")
    assert "both missed" not in meta.caption_line
    assert "Song" in meta.caption_line


def test_skips_local_and_empty():
    assert track_from_api({"track": {"id": None, "name": "x"}}) is None
    assert track_from_api({"track": {"id": "1", "is_local": True, "name": "x"}}) is None
