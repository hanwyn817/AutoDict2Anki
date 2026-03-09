import datetime

from datetime_utils import parse_datetime_flexible
from main import (
    deserialize_word_entry,
    get_new_words_list,
    get_progress_cursor_word,
    serialize_word_entry,
)
from models import ProcessResult, WordEntry


def test_parse_datetime_flexible_supports_multiple_formats():
    values = [
        "2025-01-01 10:00:00",
        "2025/01/01 10:00:00",
        "2025-01-01T10:00:00",
        "2025-01-01T10:00:00Z",
    ]
    parsed = [parse_datetime_flexible(value) for value in values]

    assert all(item is not None for item in parsed)
    assert parsed[0] == datetime.datetime(2025, 1, 1, 10, 0, 0)
    assert parsed[1] == datetime.datetime(2025, 1, 1, 10, 0, 0)
    assert parsed[2] == datetime.datetime(2025, 1, 1, 10, 0, 0)
    assert parsed[3] == datetime.datetime(2025, 1, 1, 10, 0, 0)


def test_get_progress_cursor_word_returns_last_word_without_fatal():
    base_time = datetime.datetime(2025, 1, 1, 10, 0, 0)
    words = [
        WordEntry(id=1, uuid="a", exp="", addtime=base_time),
        WordEntry(id=2, uuid="b", exp="", addtime=base_time + datetime.timedelta(seconds=1)),
        WordEntry(id=3, uuid="c", exp="", addtime=base_time + datetime.timedelta(seconds=2)),
    ]
    results = [
        ProcessResult(status="added", word="a"),
        ProcessResult(status="retryable_failed", word="b", reason="boom", failure_kind="ai_request_failed"),
        ProcessResult(status="added", word="c"),
    ]

    progress_word = get_progress_cursor_word(words, results)
    assert progress_word is not None
    assert progress_word.uuid == "c"


def test_get_progress_cursor_word_returns_none_with_fatal():
    base_time = datetime.datetime(2025, 1, 1, 10, 0, 0)
    words = [
        WordEntry(id=1, uuid="a", exp="", addtime=base_time),
        WordEntry(id=2, uuid="b", exp="", addtime=base_time + datetime.timedelta(seconds=1)),
    ]
    results = [
        ProcessResult(status="added", word="a"),
        ProcessResult(status="fatal_failed", word="b", reason="boom", failure_kind="config_error"),
    ]

    assert get_progress_cursor_word(words, results) is None


def test_get_new_words_list_filters_with_cursor_uuid(monkeypatch):
    base_time = datetime.datetime(2025, 1, 1, 10, 0, 0)
    all_words = [
        WordEntry(id=1, uuid="a", exp="", addtime=base_time),
        WordEntry(id=2, uuid="b", exp="", addtime=base_time),
        WordEntry(id=3, uuid="c", exp="", addtime=base_time),
        WordEntry(id=4, uuid="d", exp="", addtime=base_time + datetime.timedelta(seconds=1)),
    ]

    monkeypatch.setattr("main.get_valid_cookie", lambda cookie: "cookie")
    monkeypatch.setattr("main.get_all_words_data", lambda cookie: all_words)

    result = get_new_words_list((base_time, "b"))
    assert [item.uuid for item in result] == ["c", "d"]


def test_word_entry_round_trip_serialization():
    word = WordEntry(
        id=1,
        uuid="example",
        exp="meaning",
        addtime=datetime.datetime(2025, 1, 1, 10, 0, 0),
    )

    payload = serialize_word_entry(word)
    restored = deserialize_word_entry(payload)

    assert restored == word
