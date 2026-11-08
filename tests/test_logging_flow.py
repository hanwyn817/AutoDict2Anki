import logging
from datetime import datetime

import pytest
import requests

import main
from http_utils import request_with_retry
from log_utils import get_log_context, log_context
from models import ProcessResult, WordEntry


def word(name="example"):
    return WordEntry(id=1, uuid=name, exp="", addtime=datetime(2025, 1, 2))


@pytest.mark.parametrize("method", ["ankiconnect", "ankiweb"])
def test_batch_stages_and_single_success_message(monkeypatch, caplog, method):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(main.config, "ANKI_SYNC_METHOD", method)

    def lookup(*args):
        assert any("正在查询本地词典" in message for message in caplog.messages)
        return "<div>definition</div>"

    def add(*args, **kwargs):
        assert caplog.messages[-1] == f"[新增词 1/1][example] 正在写入 {'AnkiWeb' if method == 'ankiweb' else 'AnkiConnect'}"
        assert not any("添加成功" in message for message in caplog.messages)
        return {}

    class Session:
        closed = False

        def open(self):
            return None

        add_card = staticmethod(add)

        def close(self):
            self.closed = True

    session = Session()
    monkeypatch.setattr(main, "AnkiWebSession", lambda: session)
    monkeypatch.setattr(main, "get_word_definition", lookup)
    monkeypatch.setattr(main, "add_card_to_anki_by_ankiConnect", add)

    def check(*args):
        assert method == "ankiconnect"
        assert caplog.messages[-1].endswith("正在检查 AnkiConnect 牌组中是否重复")
        return True

    monkeypatch.setattr(main, "can_add_card", check)
    results, queue = main.process_new_words_with_retry([word()], "Deck")

    assert results[0].status == "added"
    assert queue == []
    assert sum("开始处理" in message for message in caplog.messages) == 1
    assert sum("添加成功" in message for message in caplog.messages) == 1
    assert any("[新增词 1/1][example] 添加成功" in message for message in caplog.messages)
    assert any("检查 AnkiConnect" in message for message in caplog.messages) == (method == "ankiconnect")
    assert session.closed == (method == "ankiweb")
    assert get_log_context() == {}


def test_duplicate_and_abort_have_terminal_logs(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(main.config, "ANKI_SYNC_METHOD", "ankiconnect")
    checked = []

    def check(name, deck):
        checked.append(name)
        if name == "offline":
            raise requests.exceptions.ConnectionError("offline")
        return False

    monkeypatch.setattr(main, "can_add_card", check)
    results = main.process_words([word("duplicate"), word("offline"), word("unstarted")], "Deck")

    assert checked == ["duplicate", "offline"]
    assert [result.status for result in results] == ["skipped_duplicate", "fatal_failed", "fatal_failed"]
    assert any("[单词处理 1/3][duplicate] 重复跳过" in message for message in caplog.messages)
    assert any("[单词处理 2/3][offline] 处理中止" in message for message in caplog.messages)
    assert any("[单词处理 3/3][unstarted] 未处理，批次已中止" in message for message in caplog.messages)
    assert not any("添加成功" in message for message in caplog.messages)


def test_missing_dictionary_warns_once_and_retry_batch_is_distinct(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(main.config, "ANKI_SYNC_METHOD", "ankiconnect")
    monkeypatch.setattr(main.config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(main, "can_add_card", lambda *args: True)
    monkeypatch.setattr(main, "add_card_to_anki_by_ankiConnect", lambda *args: {})

    def lookup(*args):
        raise FileNotFoundError("mdx missing")

    attempts = {}

    def ai(name, key):
        attempts[name] = attempts.get(name, 0) + 1
        if name == "retry" and attempts[name] == 1:
            raise requests.exceptions.Timeout("timeout")
        return "definition"

    monkeypatch.setattr(main, "get_word_definition", lookup)
    monkeypatch.setattr(main, "formatted_word_data", ai)
    results, queue = main.process_new_words_with_retry([word("retry"), word("ok")], "Deck")

    assert all(result.status == "added" for result in results)
    assert queue == []
    warnings = [message for message in caplog.messages if "本地词典文件不存在" in message]
    assert len([message for message in warnings if "[新增词" in message]) == 1
    assert any("[新增词 1/2][retry] 处理失败" in message for message in caplog.messages)
    assert any("[立即重试 1/1][retry] 添加成功" in message for message in caplog.messages)

    main.process_retry_queue([word("history")], "Deck")
    assert any("[历史重试 1/1][history] 添加成功" in message for message in caplog.messages)


@pytest.mark.parametrize("failure", ["timeout", "503"])
def test_http_retry_is_logged_before_wait_and_preserves_context(monkeypatch, caplog, failure):
    caplog.set_level(logging.INFO)
    events = []

    def sleep(delay):
        assert "0.5 秒后重试请求，第 2/2 次" in caplog.messages[-1]
        events.append("wait")

    monkeypatch.setattr("http_utils.time.sleep", sleep)

    def request(*args, **kwargs):
        events.append("request")
        response = requests.Response()
        response.status_code = 200
        if events == ["request"]:
            if failure == "timeout":
                raise requests.exceptions.Timeout("private detail")
            response.status_code = 503
        return response

    with log_context(batch="新增词", progress="2/3", word="example"):
        request_with_retry(
            "POST", "https://api.example.com/private-key?token=secret",
            max_retries=2, request_func=request, request_label="AI",
        )

    assert events == ["request", "wait", "request"]
    assert "[新增词 2/3][example] AI" in caplog.messages[0]
    assert "secret" not in caplog.text
    assert "private" not in caplog.text
    assert get_log_context() == {}


def test_result_saved_message_requires_successful_write(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    # A directory cannot be opened as the report file.
    with pytest.raises(OSError):
        main.write_result([], [], [], None, datetime.now(), datetime.now(), "Deck", str(tmp_path))
    assert not any("运行结果已保存" in message for message in caplog.messages)
    assert not any("任务处理结束" in message for message in caplog.messages)

    caplog.clear()
    report = tmp_path / "result.txt"
    main.write_result([], [], [], None, datetime.now(), datetime.now(), "Deck", str(report))
    assert report.exists()
    assert any("运行结果已保存" in message for message in caplog.messages)


@pytest.fixture
def job_setup(monkeypatch):
    monkeypatch.setattr(main, "ensure_initial_cursor_file", lambda: None)
    monkeypatch.setattr(main, "get_last_sync_cursor", lambda: (datetime(2025, 1, 1), "old"))
    monkeypatch.setattr(main, "load_failed_words_queue", lambda: [])
    monkeypatch.setattr(main, "sc_send", lambda *args: None)


@pytest.mark.parametrize("method", ["ankiconnect", "ankiweb"])
def test_eudict_connection_failure_is_not_reported_as_anki(monkeypatch, caplog, job_setup, method):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(main.config, "ANKI_SYNC_METHOD", method)

    def fetch(*args):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(main, "get_new_words_list", fetch)
    main.job()

    assert "连接欧路词典失败" in caplog.text
    assert "连接 Anki" not in caplog.text


def test_failed_queue_save_does_not_log_success_or_advance_cursor(monkeypatch, caplog, job_setup):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(main, "get_new_words_list", lambda *args: [word()])
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda *args: (
        [ProcessResult(status="retryable_failed", word="example")], [word()],
    ))

    def save(*args):
        assert "失败队列已保存" not in caplog.text
        raise OSError("disk full")

    def advance(*args):
        pytest.fail("Must not advance cursor after queue save fails")

    monkeypatch.setattr(main, "save_failed_words_queue", save)
    monkeypatch.setattr(main, "set_last_sync_cursor", advance)
    main.job()

    assert "disk full" in caplog.text
    assert "失败队列已保存" not in caplog.text


def test_logging_context_is_restored_after_exception():
    with log_context(batch="outer"):
        with pytest.raises(ValueError):
            with log_context(word="inner"):
                raise ValueError("test")
        assert get_log_context() == {"batch": "outer"}
    assert get_log_context() == {}
