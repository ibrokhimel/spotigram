from spotigram.downloader import search_query, ytdlp_format_args
from spotigram.telegram_send import safe_filename
from spotigram.models import TrackMeta
from spotigram.progress import bar, classify_line, parse_percent


def test_bar_empty_and_full():
    assert bar(None, 10) == "░" * 10
    assert bar(0, 10) == "░" * 10
    assert bar(100, 10) == "█" * 10
    assert "█" in bar(50, 10)
    assert "░" in bar(50, 10)


def test_parse_percent():
    assert parse_percent("Downloading 42.0%") == 42.0
    assert parse_percent("[download] 100% of 3.2MiB") == 100.0
    assert parse_percent("no numbers here") is None
    assert parse_percent("999%") is None


def test_safe_filename():
    assert safe_filename("wiv - i love u.m4a") == "wiv - i love u.m4a"
    assert "/" not in safe_filename("a/b\\c.m4a")
    assert safe_filename("") == "audio.m4a"


def test_mp3_args_force_mp3_not_webm():
    args = ytdlp_format_args("mp3")
    assert "--audio-format" in args
    assert "mp3" in args
    joined = " ".join(args)
    assert "251" not in joined or "-x" in args


def test_original_prefers_m4a():
    args = " ".join(ytdlp_format_args("m4a"))
    assert "140" in args
    assert "m4a" in args


def test_search_query():
    track = TrackMeta(
        id="x",
        name="i love u.",
        artists="wiv",
        album="",
        duration_ms=0,
        cover_url=None,
        url="https://open.spotify.com/track/x",
    )
    q = search_query(track)
    assert "wiv" in q
    assert "i love u." in q


def test_classify_line():
    assert classify_line("Processing query: https://open.spotify.com/track/x") == "Searching for a match…"
    assert classify_line("Downloading song") == "Downloading audio…"
    assert classify_line("Converting with ffmpeg") == "Converting with FFmpeg…"
