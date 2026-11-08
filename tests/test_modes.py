import io
import json
import logging
from dataclasses import asdict
from datetime import datetime

import pytest

import anki
import config
import interactive
import main
from events import emit, listen
from models import ProcessResult, WordEntry
from profiles import Profile, activate
from terminal_progress import Progress, display


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    return Profile(name="测试任务", deck="Test", strategy="ai_only", style="simple",
                   note_type="English", front_field="Front", back_field="Back")


def test_profile_roundtrip_and_scoped_restore(profile):
    profile.save()
    assert Profile.load(profile.name) == profile
    original = config.ANKI_DECK_NAME, main.CURSOR_FILE_PATH
    with pytest.raises(RuntimeError):
        with activate(profile):
            assert config.ANKI_DECK_NAME == "Test"
            assert main.CURSOR_FILE_PATH == str(profile.directory / "last_run_time.txt")
            raise RuntimeError("cancel")
    assert (config.ANKI_DECK_NAME, main.CURSOR_FILE_PATH) == original
    assert "API_KEY" not in (profile.directory / "config.json").read_text()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "", "..", "a/b"])
def test_profile_rejects_path_escape(name):
    with pytest.raises(ValueError):
        Profile(name=name).validate()


def test_anki_uses_selected_model_and_fields(profile, monkeypatch):
    payloads = []
    def invoke(payload):
        payloads.append(payload)
        return {"result": [True], "error": None}
    monkeypatch.setattr(anki, "_invoke_anki_connect", invoke)
    with activate(profile):
        assert anki.can_add_card("hello", "Test")
        anki.add_card_to_anki_by_ankiConnect("hello", "definition", "Test")
    note = payloads[1]["params"]["note"]
    assert note["modelName"] == "English"
    assert note["fields"] == {"Front": "hello", "Back": "definition"}
    assert payloads[0]["params"]["notes"][0]["modelName"] == "English"


def test_ai_only_never_reads_dictionary(profile, monkeypatch):
    monkeypatch.setattr(main, "get_word_definition", lambda *a: pytest.fail("dictionary called"))
    monkeypatch.setattr(main, "formatted_word_data", lambda *a: "meaning")
    monkeypatch.setattr(main, "add_card_to_anki_by_ankiConnect", lambda *a: {})
    monkeypatch.setattr(config, "AI_API_KEY", "test")
    with activate(profile):
        result = main.process_word(WordEntry(None, "hello", "", datetime.now()), "Test")
    assert result.status == "added"


def test_dictionary_only_does_not_fall_back_to_ai(profile, monkeypatch):
    profile.strategy = "dictionary_only"
    monkeypatch.setattr(main, "get_word_definition", lambda *a: None)
    monkeypatch.setattr(main, "formatted_word_data", lambda *a: pytest.fail("AI called"))
    with activate(profile):
        result = main.process_word(WordEntry(None, "absent", "", datetime.now()), "Test")
    assert result.failure_kind == "definition_empty"


def test_manual_words_keep_phrases_and_remove_duplicates():
    words = interactive.parse_words("hello,hello\ntake off，世界\n")
    assert [word.uuid for word in words] == ["hello", "take off", "世界"]


def test_plain_progress_has_no_ansi_or_info_spam():
    stream = io.StringIO()
    progress = Progress(1, stream=stream)
    progress.event(dict(kind="stage", word="hello", stage="AI"))
    assert stream.getvalue() == ""
    progress.event(dict(kind="result", result=ProcessResult("added", "hello")))
    assert "[1/1]" in stream.getvalue()
    assert "\033" not in stream.getvalue()


def test_display_writes_details_and_restores_handlers(tmp_path, capsys):
    root_logger = logging.getLogger()
    before = root_logger.handlers[:]
    with display(1, tmp_path / "run.log"):
        logging.getLogger("main").info("detail hidden")
        logging.getLogger("main").warning("warning visible")
        emit("stage", stage="AI")
    assert "detail hidden" in (tmp_path / "run.log").read_text()
    assert "detail hidden" not in capsys.readouterr().err
    assert root_logger.handlers == before


def task_for(profile, source="manual"):
    word = WordEntry(None, "hello", "", datetime(2026, 1, 1))
    return {"profile": asdict(profile), "source": source,
            "pending": [main.serialize_word_entry(word)],
            "cursor": main.serialize_word_entry(word) if source == "incremental" else None}


@pytest.mark.parametrize("source", ["manual", "recent", "file", "incremental"])
def test_task_cursor_isolation(profile, monkeypatch, source):
    task = task_for(profile, source)
    path = profile.directory / "tasks" / "task.json"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda words, deck: ([ProcessResult("added", "hello")], []))
    interactive.execute_task(path, task)
    assert task["pending"] == []
    assert (profile.directory / "app_cursor.json").exists() == (source == "incremental")
    assert not (profile.directory / "last_run_time.txt").exists()


def test_interruption_checkpoints_success_and_preserves_remaining(profile, monkeypatch):
    task = task_for(profile)
    task["pending"].append(dict(task["pending"][0], uuid="world"))
    path = profile.directory / "tasks" / "task.json"
    path.parent.mkdir(parents=True)
    def process(words, deck):
        emit("result", result=ProcessResult("added", "hello"))
        raise KeyboardInterrupt()
    monkeypatch.setattr(main, "process_new_words_with_retry", process)
    with pytest.raises(KeyboardInterrupt):
        interactive.execute_task(path, task)
    stored = json.loads(path.read_text())
    assert [word["uuid"] for word in stored["pending"]] == ["world"]
    assert stored["profile"]["deck"] == "Test"


def test_fatal_batch_preserves_unprocessed_and_does_not_advance(profile, monkeypatch):
    task = task_for(profile, "incremental")
    path = profile.directory / "tasks" / "task.json"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda words, deck: ([ProcessResult("fatal_failed", "hello", "connection")], []))
    interactive.execute_task(path, task)
    assert len(task["pending"]) == 1
    assert not (profile.directory / "app_cursor.json").exists()


def test_cli_sync_profile_paths(profile, monkeypatch):
    profile.save()
    observed = []
    monkeypatch.setattr(main, "job", lambda: observed.append((config.ANKI_DECK_NAME, main.CURSOR_FILE_PATH)))
    assert main.cli(["sync", "--profile", profile.name]) == 0
    assert observed == [("Test", str(profile.directory / "last_run_time.txt"))]


def test_wizard_back_returns_to_previous_step(profile, monkeypatch):
    monkeypatch.setattr(interactive, "catalog_for", lambda p: (["Test"], {"English": ["Front", "Back"]}))
    monkeypatch.setattr(config, "AI_API_KEY", "test")
    # manual → input → method → back at deck → method → deck → note → field → style → strategy → exam → name
    answers = iter(["3", "take off", "", "1", "b", "1", "1", "1", "1", "2", "2", "雅思", "测试任务"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers, "q"))
    state = interactive.wizard(profile)
    assert state["text"] == "take off"
    assert profile.front_field == "Front"
    assert profile.style == "simple"


def test_complete_interactive_manual_task(profile, monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "test")
    monkeypatch.setattr(interactive, "catalog_for", lambda p: (["Test"], {"English": ["Front", "Back"]}))
    monkeypatch.setattr(interactive, "get_catalog", lambda: (["Test"], {"English": ["Front", "Back"]}))
    monkeypatch.setattr(main, "can_add_card", lambda *a: True)
    monkeypatch.setattr(main, "formatted_word_data", lambda *a: "<p>meaning</p>")
    writes = []
    monkeypatch.setattr(main, "add_card_to_anki_by_ankiConnect", lambda *a: writes.append((a, config.ANKI_NOTE_TYPE)) or {})
    profile.save()
    answers = iter(["2", "3", "hello", "", "1", "1", "1", "1", "2", "2", "雅思", "测试任务", "1"])
    # Editing the loaded profile updates it without a second name-conflict prompt.
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers, "q"))
    assert interactive.run_app(profile_name=profile.name) == 0
    assert writes == [(("hello", "<p>meaning</p>", "Test"), "English")]
    records = list((profile.directory / "tasks").glob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["pending"] == []
    assert not (profile.directory / "app_cursor.json").exists()


def test_tty_progress_refresh_and_warning_keep_three_lines(monkeypatch):
    class TTY(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setenv("TERM", "xterm")
    stream = TTY()
    progress = Progress(2, stream=stream)
    progress.event(dict(kind="stage", word="hello", stage="正在生成 AI 释义"))
    assert "hello" in stream.getvalue()
    assert "\033[2A" in stream.getvalue()
    progress.emit(logging.LogRecord("test", logging.WARNING, "", 0, "重试中", (), None))
    assert "重试中\n" in stream.getvalue()
    assert stream.getvalue().endswith("\033[2A\r")
    progress.__exit__()


def test_retry_cannot_move_interactive_cursor_backwards(profile, monkeypatch):
    from profiles import write_json
    task = task_for(profile, "incremental")
    path = profile.directory / "tasks" / "old.json"
    path.parent.mkdir(parents=True)
    newer = {"last_addtime": "2026-10-01 00:00:00", "last_word_uuid": "newer"}
    write_json(profile.directory / "app_cursor.json", newer)
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda *a: ([ProcessResult("added", "hello")], []))
    interactive.execute_task(path, task)
    assert json.loads((profile.directory / "app_cursor.json").read_text()) == newer


def test_catalog_excludes_multi_field_types(monkeypatch):
    def fake(action, **params):
        if action == "deckNames":
            return ["Test"]
        if action == "modelNames":
            return ["Basic", "Cloze"]
        if action == "modelTemplates":
            return {"Card 1": {"Front": "{{Front}}", "Back": "{{Back}}"}}
        return ["Front", "Back"] if params["modelName"] == "Basic" else ["Text"]
    monkeypatch.setattr(anki, "invoke", fake)
    assert anki.get_catalog() == (["Test"], {"Basic": ["Front", "Back"]})


def test_simple_ai_template_renders_and_escapes(profile, monkeypatch):
    import ai
    data = {"word": "<word>", "meanings": [{"meaning": "释义", "examples": [
        {"english": "<script>test</script>", "translation": "例句"}]}]}
    monkeypatch.setattr(ai, "get_word_data_ai", lambda *a: json.dumps({"choices": [
        {"message": {"content": json.dumps(data)}}]}))
    with activate(profile):
        html = ai.formatted_word_data("word", "test")
    assert "释义" in html and "例句" in html
    assert "&lt;word&gt;" in html and "<script>" not in html
    assert "@import" not in html


def test_legacy_daemon_runs_immediately_and_cleans_schedule(monkeypatch):
    import schedule
    calls = []
    monkeypatch.setattr(main, "job", lambda: calls.append("run"))
    def stop(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(main.time, "sleep", stop)
    assert main.cli(["--daemon"]) == 0
    assert calls == ["run"]
    assert schedule.jobs == []


@pytest.mark.parametrize("existing", ["app", "profile", "global", "initial", "none"])
def test_first_incremental_defaults_to_existing_cursor(profile, monkeypatch, tmp_path, existing):
    from profiles import write_json
    from datetime_utils import parse_datetime_flexible
    monkeypatch.setattr(interactive, "require_secret", lambda *a: "cookie")
    monkeypatch.setattr(main, "get_valid_cookie", lambda value: value)
    global_cursor = tmp_path / "legacy_cursor.txt"
    monkeypatch.setattr(main, "CURSOR_FILE_PATH", str(global_cursor))
    monkeypatch.setattr(config, "INITIAL_CURSOR_TIME", "2026-01-01 00:00:00" if existing == "initial" else "")
    profile.directory.mkdir(parents=True)
    if existing in ("app", "profile", "global"):
        # Each more specific record must win over the legacy global record.
        write_json(global_cursor, {"last_addtime": "2026-01-01 00:00:00", "last_word_uuid": "done"})
    if existing in ("app", "profile"):
        write_json(profile.directory / "last_run_time.txt", {"last_addtime": "2026-02-01 00:00:00", "last_word_uuid": "done"})
    if existing == "app":
        write_json(profile.directory / "app_cursor.json", {"last_addtime": "2026-03-01 00:00:00", "last_word_uuid": "done"})
    expected = {"app": "2026-03-01 00:00:00", "profile": "2026-02-01 00:00:00"}.get(existing, "2026-01-01 00:00:00")
    def ask(label, default):
        assert default == ("" if existing == "none" else expected)
        return default or expected
    monkeypatch.setattr(interactive, "ask", ask if existing != "app" else lambda *a: pytest.fail("existing app cursor should not prompt"))
    timestamp = parse_datetime_flexible(expected)
    monkeypatch.setattr(main, "get_all_words_data", lambda cookie: [
        WordEntry(None, word, "", timestamp) for word in ("before", "done", "next")])
    words = interactive.fetch_words(profile, {"source": "incremental"})
    assert [word.uuid for word in words] == (["next"] if existing in ("app", "profile", "global") else ["before", "done", "next"])
    assert not (profile.directory / "app_cursor.json").exists() or existing == "app"


def test_missing_default_requires_explicit_number(monkeypatch, capsys):
    prompts = []
    answers = iter(["", "2"])
    def answer(prompt):
        prompts.append(prompt)
        return next(answers)
    monkeypatch.setattr("builtins.input", answer)
    assert interactive.choose("笔记类型", [("Basic", "Basic"), ("基础", "基础")], "Deleted") == "基础"
    assert len(prompts) == 2
    assert all("[1]" not in prompt for prompt in prompts)
    assert "Deleted”不存在或不可用" in capsys.readouterr().out


def test_existing_default_accepts_enter(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert interactive.choose("类型", [("Basic", "Basic"), ("基础", "基础")], "基础") == "基础"


def test_old_profile_loads_source_defaults(profile):
    from profiles import write_json
    saved = asdict(profile)
    for field in ("source", "count", "file_path"):
        saved.pop(field)
    write_json(profile.directory / "config.json", saved)
    loaded = Profile.load(profile.name)
    assert (loaded.source, loaded.count, loaded.file_path) == ("incremental", 10, "")


def test_cloze_template_detected_even_with_custom_name(monkeypatch):
    def fake(action, **params):
        if action == "deckNames":
            return ["Test"]
        if action == "modelNames":
            return ["Ordinary", "Custom"]
        if action == "modelFieldNames":
            return ["Front", "Back"]
        return {"Card": {"Front": "{{cloze:Front}}" if params["modelName"] == "Custom" else "{{Front}}"}}
    monkeypatch.setattr(anki, "invoke", fake)
    _, models = anki.get_catalog()
    assert list(models) == ["Ordinary"]
    assert "挖空题模板" in models.excluded["Custom"]


def test_saved_profile_runs_without_full_wizard(profile, monkeypatch, capsys):
    profile.method = "ankiconnect"
    profile.source, profile.count = "recent", 3
    profile.save()
    monkeypatch.setattr(config, "AI_API_KEY", "test")
    monkeypatch.setattr(interactive, "get_catalog", lambda: (["Test"], {"English": ["Front", "Back"]}))
    monkeypatch.setattr(interactive, "wizard", lambda *a, **kw: pytest.fail("full wizard should be skipped"))
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    observed = []
    def fetch(p, state):
        observed.append((state["source"], state["count"]))
        return interactive.parse_words("hello")
    monkeypatch.setattr(interactive, "fetch_words", fetch)
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda *a: ([ProcessResult("added", "hello")], []))
    assert interactive.run_app(profile_name=profile.name) == 0
    assert observed == [("recent", 3)]
    assert "欧路最近 3 个单词" in capsys.readouterr().out
    assert len(list((profile.directory / "tasks").glob("*.json"))) == 1


def test_invalid_saved_profile_returns_to_selection_before_writing(profile, monkeypatch, capsys):
    profile.method = "ankiconnect"
    profile.save()
    monkeypatch.setattr(config, "AI_API_KEY", "test")
    monkeypatch.setattr(interactive, "get_catalog", lambda: (["Other"], {"English": ["Front", "Back"]}))
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    visited = []
    def wizard(p, **kwargs):
        visited.append(p.deck)
        raise interactive.Cancel()
    monkeypatch.setattr(interactive, "wizard", wizard)
    monkeypatch.setattr(main, "process_new_words_with_retry", lambda *a: pytest.fail("must not write"))
    assert interactive.run_app(profile_name=profile.name) == 0
    assert visited == ["Test"]
    assert "所选牌组不存在" in capsys.readouterr().out
    assert not (profile.directory / "tasks").exists()


def test_source_only_selection_preserves_card_settings(profile, monkeypatch):
    answers = iter(["2", "15"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers, "q"))
    before = profile.deck, profile.note_type, profile.front_field, profile.style
    state = interactive.wizard(profile, source_only=True)
    assert (profile.source, profile.count) == ("recent", 15)
    assert state["source"] == "recent"
    assert (profile.deck, profile.note_type, profile.front_field, profile.style) == before


@pytest.mark.parametrize("scenario", ["edit_original", "new_same_name", "edit_other_name"])
def test_wizard_name_conflict_distinguishes_edit_from_new(profile, monkeypatch, capsys, scenario):
    from dataclasses import replace
    profile.method = "ankiconnect"
    profile.save()
    original_name = profile.name
    target = "另一个配置" if scenario == "edit_other_name" else original_name
    if scenario == "edit_other_name":
        replace(profile, name=target).save()
    monkeypatch.setattr(config, "AI_API_KEY", "test")
    monkeypatch.setattr(interactive, "catalog_for", lambda p: (["Test"], {"English": ["Front", "Back"]}))
    answers = ["2", "10", "1", "1", "1", "1", "1", "2", "雅思", target]
    if scenario != "edit_original":
        answers.append("2")  # Explicitly replace a distinct existing configuration.
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies, "q"))
    interactive.wizard(profile, editing_name=None if scenario == "new_same_name" else original_name)
    output = capsys.readouterr().out
    assert ("同名配置已存在" in output) == (scenario != "edit_original")
    assert profile.name == target
    assert profile.style == "current"
    # The wizard itself does not overwrite files before the final task confirmation.
    assert Profile.load(original_name).style == "simple"
