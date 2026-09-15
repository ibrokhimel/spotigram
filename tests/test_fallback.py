from spotigram.fallback import other_source_label, provider_attempts


def test_youtube_then_soundcloud():
    assert provider_attempts("youtube") == [
        ("youtube-music", "youtube"),
        ("soundcloud",),
    ]


def test_soundcloud_then_youtube():
    assert provider_attempts("soundcloud") == [
        ("soundcloud",),
        ("youtube-music", "youtube"),
    ]


def test_auto_same_as_youtube():
    assert provider_attempts("auto") == provider_attempts("youtube")


def test_unknown_defaults_to_auto():
    assert provider_attempts("spotify") == provider_attempts("auto")


def test_never_includes_spotify_stream():
    for source in ("youtube", "soundcloud", "auto", "nope"):
        blob = str(provider_attempts(source)).lower()
        assert "spotify" not in blob


def test_fallback_labels():
    assert other_source_label(0, "youtube") == "YouTube"
    assert other_source_label(1, "youtube") == "SoundCloud"
    assert other_source_label(0, "soundcloud") == "SoundCloud"
    assert other_source_label(1, "soundcloud") == "YouTube"
