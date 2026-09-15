from spotigram.match import parse_og_meta, pick_best_entry, score_video, search_query


def test_og_description_has_artist():
    html = """
    <meta property="og:title" content="NUTS"/>
    <meta property="og:description" content="Lil Peep, Rainhead · NUTS · Song · 2018"/>
    """
    name, artists = parse_og_meta(html)
    assert name == "NUTS"
    assert "Lil Peep" in artists


def test_search_query_includes_artist_and_audio():
    q = search_query("Lil Peep", "NUTS")
    assert "Lil Peep" in q
    assert "NUTS" in q
    assert search_query("Unknown", "NUTS") == "NUTS"


def test_comma_artists_do_not_break_youtube_query():
    from spotigram.match import search_queries

    qs = search_queries("deprezz, finest", "Versatile")
    assert qs
    assert all("," not in q for q in qs)
    assert qs[0].startswith("deprezz")
    assert "Versatile" in qs[0]


def test_prefers_song_over_food_video():
    entries = [
        {"id": "food", "title": "Everything you should know about nuts"},
        {"id": "song", "title": "Lil Peep - nuts (feat. rainy bear) (Official Audio)"},
    ]
    best = pick_best_entry(entries, "Lil Peep", "NUTS")
    assert best is not None
    assert best["id"] == "song"
    assert score_video("Everything you should know about nuts", "Lil Peep", "NUTS") < 5
