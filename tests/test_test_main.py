import test_main


def test_run_job_uses_count_argument(monkeypatch):
    calls = {"count": None}

    monkeypatch.setenv("EUDICT_WEB_COOKIE", "cookie")
    monkeypatch.setattr(test_main, "is_cookie_valid", lambda cookie: True)

    def fake_get_recent_words_list(cookie, count):
        calls["count"] = count
        return []

    monkeypatch.setattr(test_main, "get_recent_words_list", fake_get_recent_words_list)

    test_main.run_job("Deck", 23)

    assert calls["count"] == 23
