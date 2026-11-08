import json
import runpy
from pathlib import Path

import pytest
import requests

import ai


def test_default_config_uses_deepseek_official_api(monkeypatch):
    monkeypatch.delenv("AI_API_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)

    settings = runpy.run_path(str(Path(ai.__file__).with_name("config.py")))

    assert settings["AI_API_URL"] == "https://api.deepseek.com/chat/completions"
    assert settings["AI_MODEL"] == "deepseek-flash"


@pytest.mark.parametrize("api_key", ["sk-test", " Bearer sk-test ", "bearer sk-test"])
def test_deepseek_request_and_card_rendering(monkeypatch, api_key):
    word_data = {
        "word": "test",
        "meanings": [{
            "meaning": "测试",
            "examples": [{"english": "This is a test.", "translation": "这是一个测试。"}],
        }],
    }
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({
        "choices": [{"message": {"content": json.dumps(word_data)}}],
    }).encode()

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://api.deepseek.com/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
        payload = kwargs["json"]
        assert payload["model"] == "deepseek-flash"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["stream"] is False
        assert "JSON" in payload["messages"][0]["content"]
        assert payload["messages"][0]["content"].endswith("test")
        assert "top_k" not in payload
        assert "stop" not in payload
        return response

    monkeypatch.setattr(ai.config, "AI_API_URL", "https://api.deepseek.com/chat/completions")
    monkeypatch.setattr(ai.config, "AI_MODEL", "deepseek-flash")
    monkeypatch.setattr(ai, "request_with_retry", fake_request)

    html = ai.formatted_word_data("test", api_key)

    assert "This is a test." in html
    assert "这是一个测试。" in html
    assert "测试" in html


@pytest.mark.parametrize("api_key", [None, "", "  ", "Bearer "])
def test_empty_key_fails_before_request(monkeypatch, api_key):
    def unexpected_request(*args, **kwargs):
        pytest.fail("An empty API key must not trigger an HTTP request")

    monkeypatch.setattr(ai, "request_with_retry", unexpected_request)

    with pytest.raises(ValueError, match="AI_API_KEY 未配置"):
        ai.get_word_data_ai("test", api_key)


def test_deepseek_http_error_is_propagated(monkeypatch):
    response = requests.Response()
    response.status_code = 401
    monkeypatch.setattr(ai, "request_with_retry", lambda *args, **kwargs: response)

    with pytest.raises(requests.exceptions.HTTPError):
        ai.get_word_data_ai("test", "sk-invalid")
