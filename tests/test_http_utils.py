import requests

from http_utils import request_with_retry


class DummyResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"http error {self.status_code}")


def test_request_with_retry_retries_timeout_then_success():
    calls = {"count": 0}

    def fake_request(method, url, timeout=None, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.exceptions.Timeout("timeout")
        return DummyResponse(status_code=200)

    response = request_with_retry(
        "GET",
        "https://example.com",
        max_retries=3,
        backoff_factor=0,
        request_func=fake_request,
    )

    assert response.status_code == 200
    assert calls["count"] == 3


def test_request_with_retry_raises_after_max_retries_on_timeout():
    def fake_request(method, url, timeout=None, **kwargs):
        raise requests.exceptions.Timeout("timeout")

    try:
        request_with_retry(
            "GET",
            "https://example.com",
            max_retries=2,
            backoff_factor=0,
            request_func=fake_request,
        )
        assert False, "Expected Timeout exception"
    except requests.exceptions.Timeout:
        assert True


def test_request_with_retry_retries_on_503_then_success():
    calls = {"count": 0}

    def fake_request(method, url, timeout=None, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return DummyResponse(status_code=503)
        return DummyResponse(status_code=200)

    response = request_with_retry(
        "GET",
        "https://example.com",
        max_retries=3,
        backoff_factor=0,
        request_func=fake_request,
    )

    assert response.status_code == 200
    assert calls["count"] == 2
