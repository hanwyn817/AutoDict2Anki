from datetime import datetime

from main import process_word, process_words
from models import WordEntry


def test_process_word_returns_failed_when_mdx_missing(monkeypatch):
    called = {"add_called": False}

    def fake_get_word_definition(word, path):
        raise FileNotFoundError("mdx missing")

    def fake_add_card(*args, **kwargs):
        called["add_called"] = True
        return {"error": None}

    monkeypatch.setattr("main.get_word_definition", fake_get_word_definition)
    monkeypatch.setattr("main.add_card_to_anki_by_ankiConnect", fake_add_card)

    result = process_word(
        WordEntry(id=1, uuid="test", exp="", addtime=datetime.now()),
        "Deck",
    )

    assert result.status == "failed"
    assert "mdx missing" in result.reason
    assert called["add_called"] is False


def test_process_words_duplicate_is_skipped(monkeypatch):
    monkeypatch.setattr("main.can_add_card", lambda word, deck: False)

    results = process_words(
        [WordEntry(id=1, uuid="dup_word", exp="", addtime=datetime.now())],
        "Deck",
    )

    assert len(results) == 1
    assert results[0].status == "skipped_duplicate"
    assert results[0].word == "dup_word"
