from spotigram.oauth import parse_callback_url


def test_full_redirect():
    got = parse_callback_url(
        "http://127.0.0.1:8888/callback?code=ABC123&state=xyz"
    )
    assert got == ("ABC123", "xyz")


def test_https_and_extra_params():
    got = parse_callback_url(
        "https://127.0.0.1:8888/callback?state=st&code=cd&foo=1"
    )
    assert got == ("cd", "st")


def test_garbage():
    assert parse_callback_url("hello") is None
    assert parse_callback_url("http://127.0.0.1:8888/callback?code=only") is None
    assert parse_callback_url("") is None
