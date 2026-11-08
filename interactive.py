"""交互制卡向导。单词任务在写入前保存，取消和重试不会丢失目标配置。"""
import datetime
import json
import getpass
import os
import re
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import config
import main
from anki import get_catalog
from anki_web import AnkiWebSession
from datetime_utils import parse_datetime_flexible
from models import WordEntry
from profiles import Profile, activate, root, validate_name, write_json
from terminal_progress import display


class Back(Exception):
    pass


class Cancel(Exception):
    pass


def ask(label, default=""):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}（b 返回 / q 退出）: ").strip()
    if value.lower() == "b":
        raise Back()
    if value.lower() == "q":
        raise Cancel()
    return value or default


_UNSET = object()


def choose(label, options, default=_UNSET):
    if not options:
        raise ValueError(f"{label}没有可用选项")
    print(f"\n{label}")
    for index, (_, text) in enumerate(options, 1):
        print(f"  {index}. {text}")
    default_index = "1" if default is _UNSET else next(
        (str(i) for i, (key, _) in enumerate(options, 1) if key == default), "")
    if default is not _UNSET and not default_index:
        print(f"原配置的选项“{default}”不存在或不可用，请重新输入编号选择。")
    while True:
        value = ask("请选择编号", default_index)
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1][0]
        print("请输入列表中的编号。")


def positive(label, default):
    while True:
        value = ask(label, str(default))
        if value.isdigit() and int(value) > 0:
            return int(value)
        print("请输入大于 0 的整数。")


def parse_words(text):
    # 一个词组占一行；英文或中文逗号也可以分隔单词。
    words = list(dict.fromkeys(word.strip() for word in re.split(r"[\n,，]+", text) if word.strip()))
    now = datetime.datetime.now()
    return [WordEntry(id=None, uuid=word, exp="", addtime=now) for word in words]


def web_session():
    session = AnkiWebSession()
    try:
        error = session.open()
        if error:
            raise RuntimeError(error)
        return session
    except BaseException:
        session.close()
        raise


def require_secret(name, label, current=""):
    if current:
        return current
    value = getpass.getpass(f"{label} / {name}（仅本次进程使用，不回显；留空取消）: ").strip()
    if not value:
        raise Cancel()
    return value


def catalog_for(profile):
    if profile.method == "ankiconnect":
        return get_catalog()
    session = web_session()
    try:
        return session.get_catalog()
    finally:
        session.close()


def preflight(profile):
    profile.validate()
    if profile.strategy != "ai_only" and not Path(config.MDX_FILE_PATH).is_file():
        if profile.strategy == "dictionary_only":
            raise ValueError("本地词典不存在，请配置 MDX_FILE_PATH 或选择其他释义方式")
        print("提示：本地词典不存在，本次将使用 AI。")
    if profile.strategy != "dictionary_only" and not config.AI_API_KEY:
        raise ValueError("请先在 .env 中填写 AI_API_KEY，或选择仅本地词典")
    if profile.method == "ankiconnect":
        decks, models = get_catalog()
        if profile.deck not in decks:
            raise ValueError("所选牌组不存在，请先在 Anki 中创建，再返回选择")
        if profile.note_type not in models:
            reason = getattr(models, "excluded", {}).get(profile.note_type, "不存在")
            raise ValueError(f"笔记类型“{profile.note_type}”不可用：{reason}")
        if set(models[profile.note_type]) != {profile.front_field, profile.back_field}:
            raise ValueError("笔记类型字段发生变化，请返回重新选择字段映射")
    else:
        session = web_session()
        try:
            fields = session.validate_target(profile.deck, profile.note_type)
            if fields != [profile.front_field, profile.back_field]:
                raise ValueError("AnkiWeb 笔记字段或顺序发生变化，请重新选择笔记类型")
        finally:
            session.close()


def source_state(profile):
    return {"source": profile.source, "count": profile.count, "text": "", "path": profile.file_path, "catalog": None}


def wizard(profile, state=None, source_only=False, editing_name=None):
    state = source_state(profile) if state is None else state

    def source():
        state["source"] = choose("单词从哪里来？", [
            ("incremental", "欧路生词本新增单词"), ("recent", "欧路最近 N 个单词"),
            ("manual", "手动输入或粘贴单词"), ("file", "从 TXT 文件导入")], state["source"])
        if state["source"] == "recent":
            state["count"] = positive("单词数量", state["count"])
        elif state["source"] == "manual":
            print("每行一个单词或词组，也可以用逗号分隔；空行结束。")
            lines = []
            while True:
                line = ask("单词")
                if not line:
                    break
                lines.append(line)
            state["text"] = "\n".join(lines)
            if not parse_words(state["text"]):
                raise ValueError("没有输入单词")
        elif state["source"] == "file":
            state["path"] = ask("UTF-8 TXT 文件路径", state["path"])
            # 提前校验可读性，读取失败停留在本步骤。
            if not parse_words(Path(state["path"]).expanduser().read_text(encoding="utf-8-sig")):
                raise ValueError("文件没有可导入的单词")

    def method():
        profile.method = choose("写入方式", [("ankiconnect", "本地 Anki（请先打开 Anki）"),
                                              ("ankiweb", "AnkiWeb（需要有效 Cookie）")], profile.method)
        if profile.method == "ankiweb":
            config.ANKIWEB_COOKIE = require_secret("ANKI_WEB_COOKIE", "AnkiWeb Cookie", config.ANKIWEB_COOKIE)
        print("正在读取已有牌组和笔记类型…")
        state["catalog"] = catalog_for(profile)
        if not all(state["catalog"]):
            raise ValueError("没有可用的牌组或双字段笔记类型，请先在 Anki 中准备")

    def deck():
        decks, _ = state["catalog"]
        selected = choose("目标牌组", [(name, name) for name in decks] + [(None, "输入已有牌组的完整名称")], profile.deck)
        profile.deck = selected if selected is not None else ask("已有牌组名称", profile.deck)

    def note():
        _, models = state["catalog"]
        excluded = getattr(models, "excluded", {})
        options = [(name, name) for name in models]
        if excluded:
            options.append((None, f"查看不可用类型及原因（{len(excluded)} 个）"))
        while True:
            selected = choose("Anki 笔记类型（已筛选适合单词／释义的双字段类型）", options, profile.note_type)
            if selected is not None:
                profile.note_type = selected
                break
            for name, reason in excluded.items():
                print(f"  {name}：{reason}")
        fields = models[profile.note_type]
        if profile.method == "ankiconnect":
            profile.front_field = choose("哪个字段存放单词？", [(f, f) for f in fields], profile.front_field)
            profile.back_field = next(f for f in fields if f != profile.front_field)
            print(f"释义将写入：{profile.back_field}")
        else:
            profile.front_field, profile.back_field = fields
            print(f"AnkiWeb：单词 → {fields[0]}；释义 → {fields[1]}。")

    def style():
        profile.style = choose("AI 释义内容样式", [("current", "当前词典样式"), ("simple", "简洁样式（内嵌排版）")], profile.style)
        print("本地 MDX 命中的内容保留原词典排版；上述样式用于 AI 生成的释义。")

    def strategy():
        profile.strategy = choose("释义方式", [("dictionary_first", "本地词典优先，AI 补充"),
                                                ("ai_only", "仅 AI"), ("dictionary_only", "仅本地词典")], profile.strategy)
        if profile.strategy != "dictionary_only":
            config.AI_API_KEY = require_secret("AI_API_KEY", "AI API Key", config.AI_API_KEY)
            profile.exam = ask("例句学习目标", profile.exam)

    def name():
        profile.name = ask("任务配置名称（用于记住选项、隔离进度）", profile.name)
        validate_name(profile.name)
        if profile.name != editing_name and (profile.directory / "config.json").exists():
            saved = Profile.load(profile.name)
            if asdict(saved) != asdict(profile):
                if choose("同名配置已存在", [("rename", "返回修改名称"), ("replace", "覆盖该配置的常用选项")]) == "rename":
                    raise ValueError("请使用其他配置名称；已有任务仍保留自己的配置快照")

    steps = [source] if source_only else [source, method, deck, note, style, strategy, name]
    index = 0
    while index < len(steps):
        try:
            steps[index]()
            index += 1
        except Back:
            index = max(0, index - 1)
        except (ValueError, OSError, RuntimeError) as exc:
            print(f"无法继续：{exc}")
        except Exception as exc:
            print(f"连接或读取失败：{exc}")
    profile.source, profile.count, profile.file_path = state["source"], state["count"], state["path"]
    return state


def fetch_words(profile, state):
    source = state["source"]
    if source == "manual":
        return parse_words(state["text"])
    if source == "file":
        return parse_words(Path(state["path"]).expanduser().read_text(encoding="utf-8-sig"))
    cookie_value = require_secret("EUDICT_WEB_COOKIE", "欧路 Cookie", os.environ.get("EUDICT_WEB_COOKIE", ""))
    cookie = main.get_valid_cookie(cookie_value)
    if source == "recent":
        return main.get_recent_words_list(cookie, state["count"])
    cursor_path = profile.directory / "app_cursor.json"
    if cursor_path.exists():
        cursor = main._parse_cursor_file_content(cursor_path.read_text(encoding="utf-8"))
    else:
        print("首次交互增量采集：默认承接已有同步进度，之后分别保存。")
        previous_cursor = None
        for previous_path in (profile.directory / "last_run_time.txt", Path(main.CURSOR_FILE_PATH)):
            if previous_path.exists():
                previous_cursor = main._parse_cursor_file_content(previous_path.read_text(encoding="utf-8"))
                print(f"已读取上次同步进度：{previous_path}")
                break
        default_time = previous_cursor[0].isoformat(sep=" ") if previous_cursor else config.INITIAL_CURSOR_TIME
        if not default_time:
            print("尚无上次同步记录，请指定首次采集的起始时间。")
        while True:
            raw = ask("从哪个时间开始采集？", default_time)
            parsed = parse_datetime_flexible(raw)
            if parsed and parsed <= datetime.datetime.now():
                # 接受上次时间时同时继承 UUID，避免重采同一秒内已完成的词。
                cursor = previous_cursor if previous_cursor and parsed == previous_cursor[0] else (parsed, None)
                break
            print("请输入有效的过去时间，例如 2026-11-01 00:00:00")
    if cursor[0] > datetime.datetime.now():
        raise ValueError("增量游标晚于当前时间，请检查 app_cursor.json")
    words = main.get_all_words_data(cookie)
    return sorted((word for word in words if main._is_after_cursor(word, *cursor)), key=lambda w: (w.addtime, w.uuid))


def execute_task(path, task, verbose=False):
    profile = Profile(**task["profile"])
    words = [main.deserialize_word_entry(word) for word in task["pending"]]
    results = []
    # 每个结果持久化，用户中断后只保留失败和尚未完成的词。
    def checkpoint(event):
        if event["kind"] != "result":
            return
        result = event["result"]
        if result.status in ("added", "skipped_duplicate"):
            task["pending"] = [word for word in task["pending"] if word["uuid"] != result.word]
        recorded = {item["word"]: item for item in task.get("results", [])}
        recorded[result.word] = asdict(result)
        task["results"] = list(recorded.values())
        write_json(path, task)

    try:
        with activate(profile), display(len(words), path.with_suffix(".log"), verbose, checkpoint):
            results, _ = main.process_new_words_with_retry(words, profile.deck)
    finally:
        if results:
            task["pending"] = [main.serialize_word_entry(word) for word, result in zip(words, results)
                               if result.status not in ("added", "skipped_duplicate")]
            task["results"] = [asdict(result) for result in results]
            write_json(path, task)
    counts = {status: sum(result.status == status for result in results) for status in
              ("added", "skipped_duplicate", "retryable_failed", "fatal_failed")}
    print(f"\n本轮完成：添加 {counts['added']}，重复 {counts['skipped_duplicate']}，"
          f"失败或未处理 {counts['retryable_failed'] + counts['fatal_failed']}")
    for result in results:
        if result.status not in ("added", "skipped_duplicate"):
            print(f"  {result.word}：{result.reason}")
    print(f"任务记录：{path}\n完整日志：{path.with_suffix('.log')}")
    if task["source"] == "incremental" and task.get("cursor") and not main.has_fatal_result(results):
        # 失败词已先存入任务记录，之后才允许推进游标；重试旧任务不得回退游标。
        cursor_path = profile.directory / "app_cursor.json"
        candidate = main.deserialize_word_entry(task["cursor"])
        current = main._parse_cursor_file_content(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else None
        if current is None or main._is_after_cursor(candidate, *current):
            write_json(cursor_path, {"last_addtime": task["cursor"]["addtime"], "last_word_uuid": candidate.uuid})
    return task


def retry_task(verbose):
    tasks = []
    for path in sorted(root().glob("*/tasks/*.json")):
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
            profile = Profile(**task["profile"])
            profile.validate()
            if task.get("pending"):
                tasks.append((path, task))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            print(f"跳过无法读取的任务 {path}：{exc}")
    if not tasks:
        print("没有待重试的交互任务。后台失败队列由 sync / daemon 处理。")
        return
    index = choose("选择失败或中断的任务", [(i, f"{task['profile']['name']} → {task['profile']['deck']} · {len(task['pending'])} 词 · {path.stem}")
                                           for i, (path, task) in enumerate(tasks)])
    path, task = tasks[index]
    retry_profile = Profile(**task["profile"])
    if retry_profile.method == "ankiweb":
        config.ANKIWEB_COOKIE = require_secret("ANKI_WEB_COOKIE", "AnkiWeb Cookie", config.ANKIWEB_COOKIE)
    if retry_profile.strategy != "dictionary_only":
        config.AI_API_KEY = require_secret("AI_API_KEY", "AI API Key", config.AI_API_KEY)
    preflight(retry_profile)
    execute_task(path, task, verbose)


def prepare_credentials(profile):
    if profile.method == "ankiweb":
        config.ANKIWEB_COOKIE = require_secret("ANKI_WEB_COOKIE", "AnkiWeb Cookie", config.ANKIWEB_COOKIE)
    if profile.strategy != "dictionary_only":
        config.AI_API_KEY = require_secret("AI_API_KEY", "AI API Key", config.AI_API_KEY)


def profile_summary(profile):
    sources = {"incremental": "欧路新增单词", "recent": f"欧路最近 {profile.count} 个单词",
               "manual": "手动输入单词", "file": f"TXT 文件：{profile.file_path or '待选择'}"}
    styles = {"current": "当前词典样式", "simple": "简洁样式"}
    strategies = {"dictionary_first": "本地词典优先，AI 补充", "ai_only": "仅 AI", "dictionary_only": "仅本地词典"}
    print(f"\n常用配置：{profile.name}\n单词来源：{sources[profile.source]}\n"
          f"目标牌组：{profile.deck}（{profile.method}）\n"
          f"笔记类型：{profile.note_type}（单词 → {profile.front_field}；释义 → {profile.back_field}）\n"
          f"样式：{styles[profile.style]} · 释义：{strategies[profile.strategy]} · 学习目标：{profile.exam}")


def run_app(verbose=False, profile_name=None):
    print("AutoDict2Anki · 交互制卡\n随时输入 b 返回、q 退出；Ctrl+C 可取消，执行中的任务会保留供重试。")
    if not sys.stdin.isatty():
        print("提示：当前为普通输入环境，进度会使用简洁逐行输出。")
    try:
        if profile_name:
            profile = Profile.load(profile_name)
            quick = True
        else:
            action = choose("开始", [("new", "新建制卡任务"), ("retry", "重试失败或中断的任务")])
            if action == "retry":
                retry_task(verbose)
                return 0
            names = sorted(path.parent.name for path in root().glob("*/config.json"))
            selected = choose("使用任务配置", [(None, "新配置")] + [(name, name) for name in names]) if names else None
            profile = Profile.load(selected) if selected else Profile()
            quick = selected is not None
        editing_name = profile.name if quick else None
        state = source_state(profile)
        while True:
            quick_start = False
            try:
                if quick:
                    profile_summary(profile)
                    action = choose("使用此配置", [("run", "开始执行"), ("edit", "修改配置"),
                                                     ("source", "更换单词来源")])
                    if action == "edit":
                        quick = False
                        continue
                    if action == "source":
                        state = wizard(profile, state=state, source_only=True)
                        continue
                    if ((profile.source == "manual" and not state["text"]) or
                            (profile.source == "file" and not state["path"])):
                        state = wizard(profile, state=state, source_only=True)
                    quick_start = True
                else:
                    state = wizard(profile, state=state, editing_name=editing_name)
                prepare_credentials(profile)
                try:
                    preflight(profile)
                except (ValueError, RuntimeError) as exc:
                    print(f"配置无法使用：{exc}。请重新选择配置选项。")
                    quick = False
                    continue
                print("\n正在准备单词…")
                words = main.dedupe_words_by_uuid(fetch_words(profile, state))
                if not words:
                    if quick_start:
                        profile.save()
                    print("没有可处理的单词。")
                    return 0
                print(f"\n核对任务：{len(words)} 词 → {profile.deck}（{profile.method}）\n"
                      f"笔记类型：{profile.note_type} · 样式：{profile.style} · 释义：{profile.strategy}\n"
                      f"单词预览：{main.format_word_preview([word.uuid for word in words])}")
                if not quick_start and choose("是否开始写入？", [("start", "保存配置并开始"), ("edit", "返回调整")]) == "edit":
                    quick = False
                    continue
                profile.save()
                path = profile.directory / "tasks" / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.json"
                task = {"profile": asdict(profile), "source": state["source"],
                        "pending": [main.serialize_word_entry(word) for word in words],
                        "cursor": main.serialize_word_entry(words[-1]) if state["source"] == "incremental" else None}
                write_json(path, task)
                while True:
                    execute_task(path, task, verbose)
                    if not task["pending"] or choose("仍有未完成单词", [("exit", "保存并退出"), ("retry", "立即重试")]) == "exit":
                        return 0
            except Back:
                continue
    except (Cancel, Back, EOFError):
        print("\n已取消。")
        return 0
    except KeyboardInterrupt:
        print("\n已停止；如任务已开始，可从“重试失败或中断的任务”继续。")
        return 130
    except Exception as exc:
        print(f"\n任务未完成：{exc}", file=sys.stderr)
        return 1
