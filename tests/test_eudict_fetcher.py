from datetime import datetime

from eudict_fetcher import get_all_words_data


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._data


def test_get_all_words_data_paginates_and_skips_bad_addtime(monkeypatch):
    pages = {
        0: {
            "data": [
                {"id": i, "uuid": f"word_{i}", "exp": "", "addtime": "2025-01-01 10:00:00"}
                for i in range(200)
            ]
        },
        200: {
            "data": [
                {"id": 201, "uuid": "bad_time", "exp": "", "addtime": "bad-time"},
                {"id": 202, "uuid": "good_time", "exp": "", "addtime": "2025-01-02 10:00:00"},
            ]
        },
        400: {"data": []},
    }
    calls = {"count": 0}

    def fake_request_with_retry(method, url, timeout=None, **kwargs):
        calls["count"] += 1
        start = kwargs["params"]["start"]
        return FakeResponse(pages[start])

    monkeypatch.setattr("eudict_fetcher.request_with_retry", fake_request_with_retry)

    words = get_all_words_data("cookie", page_size=200)
    uuids = [item.uuid for item in words]

    assert len(words) == 201
    assert "bad_time" not in uuids
    assert "good_time" in uuids
    assert calls["count"] == 3
    assert isinstance(words[0].addtime, datetime)
