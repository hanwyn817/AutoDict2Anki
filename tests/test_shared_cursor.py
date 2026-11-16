import json
from dataclasses import asdict
from datetime import datetime

import pytest

import config
import interactive
import main
from models import ProcessResult, WordEntry
from profiles import Profile, activate, write_json


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "CURSOR_FILE_PATH", str(tmp_path / "global_cursor.txt"))
    monkeypatch.setattr(interactive, "require_secret", lambda *args: "cookie")
    monkeypatch.setattr(main, "get_valid_cookie", lambda value: value)
    monkeypatch.setattr(interactive, "ask", lambda *args: pytest.fail("已有进度不应再次询问起始时间"))
    profile = Profile(name="shared", deck="Test", method="ankiconnect", strategy="ai_only")
    profile.save()
    return profile


def make_task(profile, words):
    return {"profile": asdict(profile), "source": "incremental",
            "pending": [main.serialize_word_entry(word) for word in words],
            "cursor": main.serialize_word_entry(words[-1])}


def test_switching_from_app_to_background_and_back_shares_time_and_uuid(profile, monkeypatch):
    timestamp = datetime(2026, 1, 1)
    first = WordEntry(None, "a", "", timestamp)
    second = WordEntry(None, "b", "", timestamp)
    path = profile.directory / "tasks" / "first.json"
    task = make_task(profile, [first])
    write_json(path, task)
    processed = []

    def process(words, deck):
        processed.append([word.uuid for word in words])
        return [ProcessResult("added", word.uuid) for word in words], []

    monkeypatch.setattr(main, "process_new_words_with_retry", process)
    monkeypatch.setattr(main, "get_all_words_data", lambda cookie: [first, second])
    monkeypatch.setattr(main, "sc_send", lambda *args: None)
    interactive.execute_task(path, task)
    assert main.cli(["sync", "--profile", profile.name]) == 0
    assert processed == [["a"], ["b"]]
    assert interactive.fetch_words(profile, {"source": "incremental"}) == []
    with activate(profile):
        assert main.get_last_sync_cursor() == (timestamp, "b")
    assert not (profile.directory / "app_cursor.json").exists()
    assert not (profile.directory.parent.parent / "global_cursor.txt").exists()


@pytest.mark.parametrize("shared_uuid,legacy_uuid,expected", [
    (None, "b", "b"), ("a", "b", "b"), ("c", "b", "c"), ("b", "b", "b")])
def test_legacy_cursor_merges_without_rolling_back(profile, shared_uuid, legacy_uuid, expected):
    timestamp = datetime(2026, 1, 1)
    if shared_uuid:
        write_json(profile.directory / "last_run_time.txt",
                   {"last_addtime": str(timestamp), "last_word_uuid": shared_uuid})
    write_json(profile.directory / "app_cursor.json",
               {"last_addtime": str(timestamp), "last_word_uuid": legacy_uuid})
    with activate(profile):
        assert main.get_last_sync_cursor() == (timestamp, expected)
    assert not (profile.directory / "app_cursor.json").exists()


def test_background_migrates_legacy_cursor_before_fetching(profile, monkeypatch):
    write_json(profile.directory / "app_cursor.json",
               {"last_addtime": "2026-01-01 00:00:00", "last_word_uuid": "done"})
    observed = []
    monkeypatch.setattr(main, "get_new_words_list", lambda cursor: observed.append(cursor) or [])
    assert main.cli(["sync", "--profile", profile.name]) == 0
    assert observed == [(datetime(2026, 1, 1), "done")]


def test_migration_keeps_old_pending_incremental_words_fetchable(profile, monkeypatch):
    timestamp = datetime(2026, 1, 1)
    failed = WordEntry(None, "failed", "", timestamp)
    completed = WordEntry(None, "later", "", datetime(2026, 2, 1))
    task = make_task(profile, [failed, completed])
    task["pending"] = [main.serialize_word_entry(failed)]
    write_json(profile.directory / "tasks" / "old.json", task)
    write_json(profile.directory / "app_cursor.json",
               {"last_addtime": str(completed.addtime), "last_word_uuid": completed.uuid})
    # 手动任务不应影响增量进度的迁移边界。
    manual = dict(task, source="manual", pending=[main.serialize_word_entry(
        WordEntry(None, "manual", "", datetime(2025, 1, 1)))])
    write_json(profile.directory / "tasks" / "manual.json", manual)
    monkeypatch.setattr(main, "get_all_words_data", lambda cookie: [failed, completed])
    assert [word.uuid for word in interactive.fetch_words(profile, {"source": "incremental"})] == ["failed", "later"]
    with activate(profile):
        assert main.get_last_sync_cursor() == (timestamp, None)


def test_failed_migration_preserves_legacy_file_and_restores_scope(profile, monkeypatch):
    legacy_path = profile.directory / "app_cursor.json"
    write_json(legacy_path, {"last_addtime": "2026-01-01 00:00:00", "last_word_uuid": "done"})
    original_path = main.CURSOR_FILE_PATH

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(main, "set_last_sync_cursor", fail)
    with pytest.raises(OSError, match="disk full"):
        with activate(profile):
            pytest.fail("写入失败时不应启动任务")
    assert legacy_path.exists()
    assert main.CURSOR_FILE_PATH == original_path


def test_partial_failure_does_not_advance_and_successful_retry_does(profile, monkeypatch):
    timestamp = datetime(2026, 1, 1)
    words = [WordEntry(None, word, "", timestamp) for word in ("a", "b")]
    cursor_path = profile.directory / "last_run_time.txt"
    original_cursor = {"last_addtime": "2025-12-01 00:00:00", "last_word_uuid": "old"}
    write_json(cursor_path, original_cursor)
    task = make_task(profile, words)
    path = profile.directory / "tasks" / "partial.json"
    write_json(path, task)
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda *args: (
        [ProcessResult("added", "a"), ProcessResult("retryable_failed", "b", "temporary")], [words[1]]))
    interactive.execute_task(path, task)
    assert json.loads(cursor_path.read_text()) == original_cursor
    assert [item["uuid"] for item in json.loads(path.read_text())["pending"]] == ["b"]
    monkeypatch.setattr(main, "get_all_words_data", lambda cookie: words)
    assert interactive.fetch_words(profile, {"source": "incremental"}) == words
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda *args: ([ProcessResult("added", "b")], []))
    interactive.execute_task(path, task)
    with activate(profile):
        assert main.get_last_sync_cursor() == (timestamp, "b")
