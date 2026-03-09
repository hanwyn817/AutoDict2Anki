import datetime
import json
from datetime import datetime

import main
from main import (
    ensure_initial_cursor_file,
    format_word_preview,
    load_failed_words_queue,
    process_new_words_with_retry,
    process_word,
    process_words,
    save_failed_words_queue,
)
from models import ProcessResult, WordEntry


def test_process_word_falls_back_to_ai_when_mdx_missing(monkeypatch):
    called = {"add_called": False}

    def fake_get_word_definition(word, path):
        raise FileNotFoundError("mdx missing")

    def fake_formatted_word_data(word, api_key):
        return "<div>ai definition</div>"

    def fake_add_card(*args, **kwargs):
        called["add_called"] = True
        return {"error": None}

    monkeypatch.setattr("main.get_word_definition", fake_get_word_definition)
    monkeypatch.setattr("main.formatted_word_data", fake_formatted_word_data)
    monkeypatch.setattr("main.add_card_to_anki_by_ankiConnect", fake_add_card)
    monkeypatch.setattr(main.config, "AI_API_KEY", "test-key")

    result = process_word(
        WordEntry(id=1, uuid="test", exp="", addtime=datetime.now()),
        "Deck",
    )

    assert result.status == "added"
    assert called["add_called"] is True


def test_process_word_returns_fatal_when_mdx_missing_and_ai_unavailable(monkeypatch):
    monkeypatch.setattr("main.get_word_definition", lambda word, path: (_ for _ in ()).throw(FileNotFoundError("mdx missing")))
    monkeypatch.setattr(main.config, "AI_API_KEY", "")

    result = process_word(
        WordEntry(id=1, uuid="test", exp="", addtime=datetime.now()),
        "Deck",
    )

    assert result.status == "fatal_failed"
    assert result.failure_kind == "config_error"
    assert "AI_API_KEY 未配置" in result.reason


def test_process_words_duplicate_is_skipped(monkeypatch):
    monkeypatch.setattr(main.config, "ANKI_SYNC_METHOD", "ankiconnect")
    monkeypatch.setattr("main.can_add_card", lambda word, deck: False)

    results = process_words(
        [WordEntry(id=1, uuid="dup_word", exp="", addtime=datetime.now())],
        "Deck",
    )

    assert len(results) == 1
    assert results[0].status == "skipped_duplicate"
    assert results[0].word == "dup_word"


def test_process_new_words_with_retry_retries_retryable_failures(monkeypatch):
    base_time = datetime.now()
    words = [WordEntry(id=1, uuid="retry_me", exp="", addtime=base_time)]
    call_count = {"count": 0}

    def fake_process_words(input_words, deck_name):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return [
                ProcessResult(
                    status="retryable_failed",
                    word=input_words[0].uuid,
                    reason="temporary ai timeout",
                    failure_kind="ai_request_failed",
                )
            ]
        return [ProcessResult(status="added", word=input_words[0].uuid)]

    monkeypatch.setattr(main, "process_words", fake_process_words)

    results, failed_queue = process_new_words_with_retry(words, "Deck")

    assert call_count["count"] == 2
    assert [result.status for result in results] == ["added"]
    assert failed_queue == []


def test_save_and_load_failed_words_queue_round_trip(tmp_path, monkeypatch):
    queue_path = tmp_path / "failed_words_queue.json"
    monkeypatch.setattr(main, "FAILED_QUEUE_FILE_PATH", str(queue_path))

    words = [
        WordEntry(id=2, uuid="b", exp="", addtime=datetime(2025, 1, 1, 10, 0, 1)),
        WordEntry(id=1, uuid="a", exp="exp", addtime=datetime(2025, 1, 1, 10, 0, 0)),
        WordEntry(id=3, uuid="a", exp="latest", addtime=datetime(2025, 1, 1, 10, 0, 0)),
    ]

    save_failed_words_queue(words)
    loaded_words = load_failed_words_queue()

    assert [word.uuid for word in loaded_words] == ["a", "b"]
    assert loaded_words[0].exp == "latest"
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    assert [item["uuid"] for item in payload] == ["a", "b"]


def test_job_does_not_process_historical_queue_when_no_new_words(monkeypatch):
    process_retry_called = {"called": False}

    monkeypatch.setattr(main, "get_last_sync_cursor", lambda: (datetime(2025, 1, 1, 10, 0, 0), "a"))
    monkeypatch.setattr(
        main,
        "load_failed_words_queue",
        lambda: [WordEntry(id=1, uuid="queued", exp="", addtime=datetime(2025, 1, 1, 9, 0, 0))],
    )
    monkeypatch.setattr(main, "get_new_words_list", lambda cursor: [])
    monkeypatch.setattr(main, "sc_send", lambda title, body: None)

    def fake_process_retry_queue(words, deck_name):
        process_retry_called["called"] = True
        return [], []

    monkeypatch.setattr(main, "process_retry_queue", fake_process_retry_queue)

    main.job()

    assert process_retry_called["called"] is False


def test_job_saves_failed_queue_before_advancing_cursor(monkeypatch):
    call_order = []
    new_word = WordEntry(id=1, uuid="new", exp="", addtime=datetime(2025, 1, 1, 10, 0, 0))

    monkeypatch.setattr(main, "get_last_sync_cursor", lambda: (datetime(2025, 1, 1, 9, 0, 0), "old"))
    monkeypatch.setattr(main, "load_failed_words_queue", lambda: [])
    monkeypatch.setattr(main, "get_new_words_list", lambda cursor: [new_word])
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda words, deck: ([ProcessResult(status="added", word="new")], []))
    monkeypatch.setattr(main, "write_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "sc_send", lambda title, body: None)

    def fake_save_failed_words_queue(words):
        call_order.append("save_queue")

    def fake_set_last_sync_cursor(run_time, run_uuid):
        call_order.append("set_cursor")

    monkeypatch.setattr(main, "save_failed_words_queue", fake_save_failed_words_queue)
    monkeypatch.setattr(main, "set_last_sync_cursor", fake_set_last_sync_cursor)

    main.job()

    assert call_order == ["save_queue", "set_cursor"]


def test_ensure_initial_cursor_file_creates_missing_cursor(tmp_path, monkeypatch):
    cursor_path = tmp_path / "state" / "last_run_time.txt"

    monkeypatch.setattr(main, "CURSOR_FILE_PATH", str(cursor_path))
    monkeypatch.setattr(main.config, "INITIAL_CURSOR_TIME", "2025-01-01 00:00:00")

    ensure_initial_cursor_file()

    assert cursor_path.read_text(encoding="utf-8").strip() == "2025-01-01 00:00:00"


def test_ensure_initial_cursor_file_keeps_existing_cursor(tmp_path, monkeypatch):
    cursor_path = tmp_path / "last_run_time.txt"
    cursor_path.write_text("2025-02-01 00:00:00", encoding="utf-8")

    monkeypatch.setattr(main, "CURSOR_FILE_PATH", str(cursor_path))
    monkeypatch.setattr(main.config, "INITIAL_CURSOR_TIME", "2025-01-01 00:00:00")

    ensure_initial_cursor_file()

    assert cursor_path.read_text(encoding="utf-8").strip() == "2025-02-01 00:00:00"


def test_format_word_preview_limits_output():
    words = [f"word_{index}" for index in range(35)]

    preview = format_word_preview(words, limit=30)

    assert "word_0" in preview
    assert "word_29" in preview
    assert "word_30" not in preview
    assert "另有 5 个" in preview
