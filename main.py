import datetime
import json
import os
import schedule
import time
from typing import Dict, List, Optional, Tuple

import requests

import config
from ai import formatted_word_data
from anki import add_card_to_anki_by_ankiConnect, can_add_card
from anki_web import AnkiWebSession, CARD_ADD_INTERVAL, SESSION_ERROR_PREFIX
from datetime_utils import format_datetime_for_storage, parse_datetime_flexible
from eudict_fetcher import get_all_words_data, is_cookie_valid
from mdx_dict import get_word_definition
from models import ProcessResult, WordEntry
from log_utils import configure_logging, get_logger, get_log_context, log_context
from notification import sc_send

logger = get_logger(__name__)

CURSOR_FILE_PATH = config.CURSOR_FILE_PATH
FAILED_QUEUE_FILE_PATH = config.FAILED_QUEUE_FILE_PATH
RESULT_FILE_PATH = config.RESULT_FILE_PATH
RETRYABLE_FAILURE_KINDS_FOR_IMMEDIATE_RETRY = {"ai_request_failed", "ankiwrite_failed"}


def get_valid_cookie(initial_cookie: Optional[str]) -> str:
    cookie = initial_cookie or ""
    if is_cookie_valid(cookie):
        return cookie

    logger.error("当前 cookie 无效或已过期，请运行 `python login.py` 更新 Cookie。程序终止。")
    raise ValueError("当前 EUDICT_WEB_COOKIE 无效或已过期")


def _is_after_cursor(
    word: WordEntry,
    cursor_time: datetime.datetime,
    cursor_uuid: Optional[str],
) -> bool:
    if word.addtime > cursor_time:
        return True
    if word.addtime < cursor_time:
        return False
    if not cursor_uuid:
        return True
    return word.uuid > cursor_uuid


def _parse_cursor_file_content(content: str) -> Tuple[datetime.datetime, Optional[str]]:
    raw = content.strip()
    if not raw:
        raise ValueError("游标文件为空")

    if raw.startswith("{"):
        payload = json.loads(raw)
        cursor_time = parse_datetime_flexible(str(payload.get("last_addtime", "")).strip())
        if not cursor_time:
            raise ValueError("游标文件中的 last_addtime 无法解析")
        cursor_uuid = str(payload.get("last_word_uuid", "")).strip() or None
        return cursor_time, cursor_uuid

    legacy_time = parse_datetime_flexible(raw)
    if not legacy_time:
        raise ValueError("游标文件时间格式不正确")
    return legacy_time, None


def _atomic_write_text(file_path: str, content: str) -> None:
    parent_dir = os.path.dirname(file_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    temp_file_path = f"{file_path}.tmp"
    with open(temp_file_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temp_file_path, file_path)


def _build_process_result(
    status: str,
    word: str,
    reason: str = "",
    failure_kind: str = "",
) -> ProcessResult:
    return ProcessResult(status=status, word=word, reason=reason, failure_kind=failure_kind)


def _build_retryable_failure(word: WordEntry, reason: str, failure_kind: str) -> ProcessResult:
    return _build_process_result(
        status="retryable_failed",
        word=word.uuid,
        reason=reason,
        failure_kind=failure_kind,
    )


def _build_fatal_failure(word: WordEntry, reason: str, failure_kind: str) -> ProcessResult:
    return _build_process_result(
        status="fatal_failed",
        word=word.uuid,
        reason=reason,
        failure_kind=failure_kind,
    )


def _build_aborted_results(remaining_words: List[WordEntry], reason: str) -> List[ProcessResult]:
    return [
        _build_process_result(
            status="fatal_failed",
            word=word.uuid,
            reason=reason,
            failure_kind="batch_aborted",
        )
        for word in remaining_words
    ]


def _strip_session_error_prefix(reason: str) -> str:
    if SESSION_ERROR_PREFIX not in reason:
        return reason
    return reason.replace(SESSION_ERROR_PREFIX, "", 1).strip()


def serialize_word_entry(word: WordEntry) -> Dict[str, object]:
    return {
        "id": word.id,
        "uuid": word.uuid,
        "exp": word.exp,
        "addtime": format_datetime_for_storage(word.addtime),
    }


def deserialize_word_entry(payload: Dict[str, object]) -> WordEntry:
    if not isinstance(payload, dict):
        raise ValueError("队列中的条目不是对象")

    uuid = str(payload.get("uuid", "")).strip()
    if not uuid:
        raise ValueError("队列中的条目缺少 uuid")

    parsed_addtime = parse_datetime_flexible(str(payload.get("addtime", "")).strip())
    if not parsed_addtime:
        raise ValueError(f"队列中的条目 {uuid} 缺少可解析的 addtime")

    return WordEntry(
        id=payload.get("id"),
        uuid=uuid,
        exp=str(payload.get("exp", "") or ""),
        addtime=parsed_addtime,
    )


def dedupe_words_by_uuid(words: List[WordEntry]) -> List[WordEntry]:
    deduped = {}
    for word in words:
        deduped[word.uuid] = word
    return sorted(deduped.values(), key=lambda item: (item.addtime, item.uuid))


def format_word_preview(words: List[str], limit: int = 30) -> str:
    if not words:
        return ""

    preview_words = words[:limit]
    preview = ", ".join(preview_words)
    remaining_count = len(words) - len(preview_words)
    if remaining_count > 0:
        preview += f" ... 另有 {remaining_count} 个"
    return preview


def load_failed_words_queue() -> List[WordEntry]:
    try:
        with open(FAILED_QUEUE_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except FileNotFoundError:
        return []

    if not content:
        return []

    payload = json.loads(content)
    if not isinstance(payload, list):
        raise ValueError("失败队列文件内容必须是 JSON 数组")

    return dedupe_words_by_uuid([deserialize_word_entry(item) for item in payload])


def save_failed_words_queue(words: List[WordEntry]) -> None:
    serialized = [serialize_word_entry(word) for word in dedupe_words_by_uuid(words)]
    _atomic_write_text(
        FAILED_QUEUE_FILE_PATH,
        json.dumps(serialized, ensure_ascii=False, indent=2),
    )


def is_fatal_result(result: ProcessResult) -> bool:
    return result.status == "fatal_failed"


def should_enqueue_result(result: ProcessResult) -> bool:
    return result.status == "retryable_failed"


def should_retry_immediately(result: ProcessResult) -> bool:
    return result.failure_kind in RETRYABLE_FAILURE_KINDS_FOR_IMMEDIATE_RETRY


def has_fatal_result(results: List[ProcessResult]) -> bool:
    return any(is_fatal_result(result) for result in results)


def get_first_fatal_result(results: List[ProcessResult]) -> Optional[ProcessResult]:
    for result in results:
        if is_fatal_result(result):
            return result
    return None


def _log_word_result(result: ProcessResult, started_at: Optional[float] = None) -> None:
    elapsed = time.perf_counter() - started_at if started_at is not None else 0.0
    if result.status == "added":
        logger.info("添加成功，总耗时 %.1f 秒", elapsed)
    elif result.status == "skipped_duplicate":
        logger.info("重复跳过: %s，总耗时 %.1f 秒", result.reason, elapsed)
    elif result.status == "fatal_failed":
        logger.error("处理中止: %s，总耗时 %.1f 秒", result.reason, elapsed)
    else:
        logger.warning("处理失败: %s，总耗时 %.1f 秒", result.reason, elapsed)


def process_word(
    word: WordEntry, deck_name: str, ankiweb_session=None, progress: str = "",
    _started_at: Optional[float] = None,
) -> ProcessResult:
    """获取释义并写入 Anki；独立调用和批量调用共用日志上下文。"""
    with log_context(
        word=word.uuid, progress=progress,
        missing_dictionary_paths=get_log_context().get("missing_dictionary_paths", set()),
    ):
        started_at = _started_at if _started_at is not None else time.perf_counter()
        if _started_at is None:
            logger.info("开始处理")
        result = _process_word(word, deck_name, ankiweb_session, progress)
        _log_word_result(result, started_at)
        return result


def _process_word(word: WordEntry, deck_name: str, ankiweb_session=None, progress: str = "") -> ProcessResult:
    """获取单词定义并添加到 Anki。"""
    lookup_started = time.perf_counter()
    logger.info("正在查询本地词典")
    definition = None
    try:
        definition = get_word_definition(word.uuid, config.MDX_FILE_PATH)
    except FileNotFoundError:
        warned_paths = get_log_context().get("missing_dictionary_paths", set())
        if config.MDX_FILE_PATH not in warned_paths:
            logger.warning("本地词典文件不存在，本批次将按需回退到 AI: %s", config.MDX_FILE_PATH)
            warned_paths.add(config.MDX_FILE_PATH)
    except Exception as exc:
        return _build_retryable_failure(word, f"词典查询失败: {exc}", "dictionary_lookup_failed")

    if definition:
        logger.info("本地词典命中，耗时 %.1f 秒", time.perf_counter() - lookup_started)

    if not definition:
        if not config.AI_API_KEY:
            return _build_fatal_failure(word, "AI_API_KEY 未配置，无法回退到 AI 查询。", "config_error")
        try:
            ai_started = time.perf_counter()
            logger.info("本地词典无可用释义，正在调用 AI 处理（模型: %s）", config.AI_MODEL)
            definition = formatted_word_data(word.uuid, config.AI_API_KEY)
        except requests.exceptions.RequestException as exc:
            return _build_retryable_failure(word, f"AI 释义失败: {exc}", "ai_request_failed")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError) as exc:
            return _build_retryable_failure(word, f"AI 释义解析失败: {exc}", "ai_parse_failed")
        except Exception as exc:
            return _build_retryable_failure(word, f"AI 释义失败: {exc}", "ai_request_failed")
        if definition:
            logger.info("AI 释义生成并校验完成，耗时 %.1f 秒", time.perf_counter() - ai_started)

    if not definition:
        return _build_retryable_failure(word, "无法获取到释义", "definition_empty")

    write_started = time.perf_counter()
    logger.info("正在写入 %s", "AnkiWeb" if ankiweb_session else "AnkiConnect")
    try:
        if ankiweb_session:
            add_result = ankiweb_session.add_card(word.uuid, definition, deck_name, progress=progress)
        else:
            add_result = add_card_to_anki_by_ankiConnect(word.uuid, definition, deck_name)
    except requests.exceptions.ConnectionError as exc:
        return _build_fatal_failure(word, "连接 AnkiConnect 失败，请确认 Anki 已启动且插件可用。", "ankiconnect_unavailable")
    except Exception as exc:
        return _build_retryable_failure(word, f"写入 Anki 失败: {exc}", "ankiwrite_failed")

    add_error = add_result.get("error") if isinstance(add_result, dict) else "Anki 返回格式错误"
    if not add_error:
        logger.debug("Anki 写入完成，耗时 %.1f 秒", time.perf_counter() - write_started)
        return _build_process_result(status="added", word=word.uuid)

    add_error = str(add_error)
    if SESSION_ERROR_PREFIX in add_error:
        return _build_fatal_failure(
            word,
            _strip_session_error_prefix(add_error),
            "ankiweb_session_failed",
        )
    return _build_retryable_failure(word, add_error, "ankiwrite_failed")


def get_new_words_list(last_run_cursor: Tuple[datetime.datetime, Optional[str]]) -> List[WordEntry]:
    """根据游标获取新增单词列表。"""
    last_run_time, last_run_uuid = last_run_cursor
    cookie = get_valid_cookie(os.environ.get("EUDICT_WEB_COOKIE"))

    all_words_data = get_all_words_data(cookie)
    recent_words_data = [
        entry for entry in all_words_data if _is_after_cursor(entry, last_run_time, last_run_uuid)
    ]
    recent_words_data.sort(key=lambda item: (item.addtime, item.uuid))
    return recent_words_data


def get_recent_words_list(cookie: str, count: int = 10) -> List[WordEntry]:
    """获取最近新增的指定数量单词列表（用于测试脚本）。"""
    all_words_data = get_all_words_data(cookie, page_size=max(200, count))
    sorted_words = sorted(all_words_data, key=lambda x: x.addtime, reverse=True)
    return sorted_words[:count]


def process_words(words: List[WordEntry], deck_name: str) -> List[ProcessResult]:
    """处理一个批次，并为所有阶段提供统一的日志上下文。"""
    if not words:
        return []
    with log_context(
        batch=get_log_context().get("batch", "单词处理"),
        missing_dictionary_paths=get_log_context().get("missing_dictionary_paths", set()),
    ):
        return _process_words(words, deck_name)


def _process_words(words: List[WordEntry], deck_name: str) -> List[ProcessResult]:
    results: List[ProcessResult] = []
    use_ankiweb = config.ANKI_SYNC_METHOD == "ankiweb"
    ankiweb_session = None
    total = len(words)

    if use_ankiweb:
        logger.info("正在建立 AnkiWeb 会话")
        ankiweb_session = AnkiWebSession()
        open_err = ankiweb_session.open()
        if open_err:
            logger.error("AnkiWeb 会话启动失败: %s", open_err)
            for index, word in enumerate(words):
                result = _build_fatal_failure(word, open_err, "ankiweb_session_failed")
                with log_context(word=word.uuid, progress=f"{index + 1}/{total}"):
                    _log_word_result(result)
                results.append(result)
            return results
        logger.info("AnkiWeb 会话已就绪")

    try:
        for index, word in enumerate(words):
            progress = f"{index + 1}/{total}"
            with log_context(word=word.uuid, progress=progress):
                started_at = time.perf_counter()
                logger.info("开始处理")
                try:
                    can_add = True
                    if not use_ankiweb:
                        logger.info("正在检查 AnkiConnect 牌组中是否重复")
                        can_add = can_add_card(word.uuid, deck_name)
                except requests.exceptions.ConnectionError:
                    result = _build_fatal_failure(
                        word, "连接 AnkiConnect 失败，请确认 Anki 已启动且插件可用。",
                        "ankiconnect_unavailable",
                    )
                    _log_word_result(result, started_at)
                except Exception as exc:
                    result = _build_fatal_failure(word, f"写入前检查失败: {exc}", "config_error")
                    _log_word_result(result, started_at)
                else:
                    if not can_add:
                        result = _build_process_result(
                            status="skipped_duplicate", word=word.uuid,
                            reason=f"牌组 {deck_name} 中已存在",
                        )
                        _log_word_result(result, started_at)
                    else:
                        result = process_word(
                            word, deck_name, ankiweb_session, progress=progress,
                            _started_at=started_at,
                        )
                results.append(result)

            if is_fatal_result(result):
                logger.error("发生致命错误，中止批次；剩余 %s 个词未处理", total - index - 1)
                aborted = _build_aborted_results(words[index + 1:], "上一张卡片出现致命错误，已中止")
                for offset, skipped in enumerate(aborted, start=index + 2):
                    with log_context(word=skipped.word, progress=f"{offset}/{total}"):
                        logger.warning("未处理，批次已中止: %s", skipped.reason)
                results.extend(aborted)
                break

            if use_ankiweb and index < total - 1:
                logger.debug("AnkiWeb 提交间隔，等待 %s 秒", CARD_ADD_INTERVAL)
                time.sleep(CARD_ADD_INTERVAL)
    finally:
        if ankiweb_session:
            ankiweb_session.close()
            logger.debug("AnkiWeb 会话已关闭")

    return results


def process_retry_queue(words: List[WordEntry], deck_name: str) -> Tuple[List[ProcessResult], List[WordEntry]]:
    with log_context(batch="历史重试"):
        results = process_words(words, deck_name)
    remaining_words = [word for word, result in zip(words, results) if should_enqueue_result(result)]
    return results, dedupe_words_by_uuid(remaining_words)


def process_new_words_with_retry(
    words: List[WordEntry],
    deck_name: str,
) -> Tuple[List[ProcessResult], List[WordEntry]]:
    with log_context(batch="新增词", missing_dictionary_paths=set()):
        initial_results = process_words(words, deck_name)
    final_results_by_uuid = {result.word: result for result in initial_results}

    if has_fatal_result(initial_results):
        return [final_results_by_uuid[word.uuid] for word in words], []

    retry_candidates: List[WordEntry] = []
    final_failed_words: List[WordEntry] = []

    for word, result in zip(words, initial_results):
        if not should_enqueue_result(result):
            continue
        if should_retry_immediately(result):
            retry_candidates.append(word)
        else:
            final_failed_words.append(word)

    if retry_candidates:
        logger.info("开始立即重试，共 %s 个词: %s", len(retry_candidates), format_word_preview([word.uuid for word in retry_candidates]))
        with log_context(batch="立即重试"):
            retry_results = process_words(retry_candidates, deck_name)
        for retry_word, retry_result in zip(retry_candidates, retry_results):
            final_results_by_uuid[retry_word.uuid] = retry_result

        if has_fatal_result(retry_results):
            return [final_results_by_uuid[word.uuid] for word in words], []

        for retry_word, retry_result in zip(retry_candidates, retry_results):
            if should_enqueue_result(retry_result):
                final_failed_words.append(retry_word)

    final_results = [final_results_by_uuid[word.uuid] for word in words]
    return final_results, dedupe_words_by_uuid(final_failed_words)


def get_progress_cursor_word(
    new_words: List[WordEntry],
    results: List[ProcessResult],
) -> Optional[WordEntry]:
    if not new_words or has_fatal_result(results):
        return None
    return new_words[-1]


def summarize_results(results: List[ProcessResult]) -> Dict[str, List[str]]:
    summary: Dict[str, List[str]] = {
        "added": [],
        "skipped_duplicate": [],
        "retryable_failed": [],
        "fatal_failed": [],
    }

    skipped_groups: Dict[str, List[str]] = {}

    for result in results:
        if result.status == "added":
            summary["added"].append(result.word)
            continue
        if result.status == "skipped_duplicate":
            reason = result.reason or "未知牌组"
            skipped_groups.setdefault(reason, []).append(result.word)
            continue

        detail = result.word
        if result.reason:
            detail = f"{result.word}: {result.reason}"
        summary[result.status].append(detail)

    if skipped_groups:
        formatted_groups = []
        for reason, words in skipped_groups.items():
            words_str = ", ".join(words)
            if "中已存在" in reason:
                formatted_reason = reason.replace("中已存在", "中已存在重复的卡片")
            else:
                formatted_reason = f"牌组 {reason} 中已存在重复的卡片"
            formatted_groups.append(f"{formatted_reason}: {words_str}")
        summary["skipped_duplicate"] = ["; ".join(formatted_groups)]

    return summary


def write_result(
    historical_results: List[ProcessResult],
    new_results: List[ProcessResult],
    failed_queue_words: List[WordEntry],
    progress_word: Optional[WordEntry],
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    deck_name: str,
    result_file_path: Optional[str] = None,
) -> None:
    target_result_path = result_file_path or RESULT_FILE_PATH
    historical_summary = summarize_results(historical_results)
    new_summary = summarize_results(new_results)

    historical_recovered = sum(1 for r in historical_results if r.status == "added")
    historical_still_failed = sum(1 for r in historical_results if r.status == "retryable_failed")
    new_success_count = sum(1 for r in new_results if r.status == "added")
    skipped_count = sum(1 for r in new_results if r.status == "skipped_duplicate")
    new_failure_count = sum(1 for r in new_results if r.status == "retryable_failed")

    logger.info("历史失败重试成功: %s", historical_recovered)
    logger.info("本次新增成功: %s", new_success_count)
    logger.info("本次新增跳过重复: %s", skipped_count)
    logger.info("本次新增最终失败: %s", new_failure_count)
    logger.info("失败队列总数: %s", len(failed_queue_words))
    logger.info("历史失败仍失败: %s", historical_still_failed)

    result_parent_dir = os.path.dirname(target_result_path)
    if result_parent_dir:
        os.makedirs(result_parent_dir, exist_ok=True)

    with open(target_result_path, "w", encoding="utf-8") as f:
        f.write(f"目标牌组: {deck_name}\n")
        f.write(f"历史失败重试成功: {historical_recovered}\n")
        f.write(f"历史失败仍失败: {historical_still_failed}\n")
        f.write(f"本次新增成功: {new_success_count}\n")
        f.write(f"本次新增跳过重复: {skipped_count}\n")
        f.write(f"本次新增最终失败: {new_failure_count}\n")
        f.write(f"失败队列总数: {len(failed_queue_words)}\n")
        if progress_word:
            f.write(
                "游标已推进到: "
                f"{format_datetime_for_storage(progress_word.addtime)} (uuid: {progress_word.uuid})\n"
            )
        else:
            f.write("游标已推进到: 未推进\n")
        f.write(f"历史失败重试成功列表: {', '.join(historical_summary['added'])}\n")
        f.write(
            "历史失败仍失败列表: "
            f"{', '.join(historical_summary['retryable_failed'])}\n"
        )
        f.write(f"本次新增成功列表: {', '.join(new_summary['added'])}\n")
        f.write(
            "本次新增跳过列表: "
            f"{new_summary['skipped_duplicate'][0] if new_summary['skipped_duplicate'] else ''}\n"
        )
        f.write(
            "本次新增最终失败列表: "
            f"{', '.join(new_summary['retryable_failed'])}\n"
        )
        f.write(
            "失败队列单词列表: "
            f"{', '.join(word.uuid for word in failed_queue_words)}\n"
        )
        f.write(f"执行时间: {end_time - start_time}\n")

    logger.info("运行结果已保存至 %s", target_result_path)
    logger.info("任务处理结束，总耗时 %s", end_time - start_time)


def get_last_sync_cursor() -> Optional[Tuple[datetime.datetime, Optional[str]]]:
    try:
        with open(CURSOR_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except FileNotFoundError:
        return None

    if not content:
        return None

    return _parse_cursor_file_content(content)


def set_last_sync_cursor(run_time: datetime.datetime, run_uuid: Optional[str]) -> None:
    payload = {
        "last_addtime": format_datetime_for_storage(run_time),
        "last_word_uuid": run_uuid or "",
    }
    _atomic_write_text(CURSOR_FILE_PATH, json.dumps(payload, ensure_ascii=False))


def ensure_initial_cursor_file() -> None:
    if os.path.exists(CURSOR_FILE_PATH):
        return

    if not config.INITIAL_CURSOR_TIME:
        return

    initial_cursor = parse_datetime_flexible(config.INITIAL_CURSOR_TIME)
    if not initial_cursor:
        raise ValueError("INITIAL_CURSOR_TIME 格式不正确，无法解析为时间")
    if initial_cursor > datetime.datetime.now():
        raise ValueError("INITIAL_CURSOR_TIME 晚于当前时间，请改为过去时间")

    _atomic_write_text(CURSOR_FILE_PATH, config.INITIAL_CURSOR_TIME)


def _send_fatal_failure(title: str, reason: str) -> None:
    logger.error(reason)
    sc_send(title, reason)


def _handle_fatal_results(results: List[ProcessResult], default_message: str) -> None:
    fatal_result = get_first_fatal_result(results)
    if fatal_result and fatal_result.reason:
        _send_fatal_failure("AutoDict2Anki 运行失败", fatal_result.reason)
        return
    _send_fatal_failure("AutoDict2Anki 运行失败", default_message)


def job() -> None:
    logger.info("开始同步任务，方式: %s，目标牌组: %s", config.ANKI_SYNC_METHOD, config.ANKI_DECK_NAME)
    try:
        ensure_initial_cursor_file()
        last_sync_cursor = get_last_sync_cursor()
    except Exception as exc:
        _send_fatal_failure("AutoDict2Anki 运行失败", f"last_run_time.txt 中的游标格式不正确，请修正后重试。错误: {exc}")
        return

    if not last_sync_cursor:
        _send_fatal_failure("AutoDict2Anki 运行失败", "未获取到上次运行时间，请手动填写 last_run_time.txt 后再运行程序。")
        return

    try:
        historical_failed_words = load_failed_words_queue()
    except Exception as exc:
        _send_fatal_failure("AutoDict2Anki 运行失败", f"failed_words_queue.json 格式不正确，请修正后重试。错误: {exc}")
        return

    last_run_time_dt, last_run_uuid = last_sync_cursor
    if last_run_time_dt > datetime.datetime.now():
        _send_fatal_failure("AutoDict2Anki 运行失败", "last_run_time.txt 中的时间晚于当前时间，请检查并修正。")
        return

    logger.info(
        "上次运行游标: time=%s uuid=%s",
        format_datetime_for_storage(last_run_time_dt),
        last_run_uuid or "",
    )
    start_time = datetime.datetime.now()

    logger.info("正在从欧路词典拉取新增单词")
    fetch_started = time.perf_counter()
    try:
        new_words = get_new_words_list(last_sync_cursor)
    except requests.exceptions.ConnectionError:
        _send_fatal_failure("AutoDict2Anki 运行失败", "连接欧路词典失败，请检查 my.eudic.net 的网络连通性。")
        return
    except Exception as exc:
        _send_fatal_failure("AutoDict2Anki 运行失败", f"获取新单词失败: {exc}")
        return

    logger.info("新增单词拉取完成，共 %s 个，耗时 %.1f 秒；历史失败队列 %s 个", len(new_words), time.perf_counter() - fetch_started, len(historical_failed_words))
    if not new_words:
        logger.info("没有新词，本轮结束；历史失败队列未重试（%s 个），总耗时 %s", len(historical_failed_words), datetime.datetime.now() - start_time)
        return

    historical_results: List[ProcessResult] = []
    remaining_historical_queue = historical_failed_words
    if historical_failed_words:
        logger.info("开始重试历史失败词，共 %s 个。", len(historical_failed_words))
        historical_results, remaining_historical_queue = process_retry_queue(
            historical_failed_words,
            config.ANKI_DECK_NAME,
        )
        if has_fatal_result(historical_results):
            _handle_fatal_results(historical_results, "重试历史失败词时发生致命错误。")
            return

    logger.info("开始处理本次新增词，共 %s 个。", len(new_words))
    new_results, remaining_new_queue = process_new_words_with_retry(new_words, config.ANKI_DECK_NAME)
    if has_fatal_result(new_results):
        _handle_fatal_results(new_results, "处理本次新增词时发生致命错误。")
        return

    final_failed_queue = dedupe_words_by_uuid(remaining_historical_queue + remaining_new_queue)
    progress_word = get_progress_cursor_word(new_words, new_results)

    try:
        save_failed_words_queue(final_failed_queue)
        logger.info("失败队列已保存，共 %s 个词: %s", len(final_failed_queue), format_word_preview([word.uuid for word in final_failed_queue]) or "无")
    except Exception as exc:
        _send_fatal_failure("AutoDict2Anki 运行失败", f"保存 failed_words_queue.json 失败: {exc}")
        return

    try:
        if progress_word:
            set_last_sync_cursor(progress_word.addtime, progress_word.uuid)
            logger.info(
                "游标已推进到: time=%s uuid=%s",
                format_datetime_for_storage(progress_word.addtime),
                progress_word.uuid,
            )
    except Exception as exc:
        _send_fatal_failure("AutoDict2Anki 运行失败", f"更新 last_run_time.txt 失败: {exc}")
        return

    end_time = datetime.datetime.now()
    try:
        write_result(
            historical_results,
            new_results,
            final_failed_queue,
            progress_word,
            start_time,
            end_time,
            config.ANKI_DECK_NAME,
        )
    except OSError as exc:
        _send_fatal_failure("AutoDict2Anki 运行失败", f"保存运行结果失败: {exc}")
        return

    historical_recovered = sum(1 for r in historical_results if r.status == "added")
    new_success_count = sum(1 for r in new_results if r.status == "added")
    skipped_count = sum(1 for r in new_results if r.status == "skipped_duplicate")
    new_failure_count = sum(1 for r in new_results if r.status == "retryable_failed")
    historical_summary = summarize_results(historical_results)
    new_summary = summarize_results(new_results)

    title = (
        "AutoDict2Anki 运行完成 "
        f"(历史补救 {historical_recovered}, 本次成功 {new_success_count}, 本次失败 {new_failure_count})"
    )
    desp = f"**目标牌组**: {config.ANKI_DECK_NAME}\n\n"
    if progress_word:
        new_time_str = format_datetime_for_storage(progress_word.addtime)
        desp += f"**游标已推进到**: {new_time_str} (uuid: {progress_word.uuid})\n\n"
    desp += f"**历史失败重试成功** ({historical_recovered}): {format_word_preview(historical_summary['added'])}\n\n"
    desp += f"**本次新增成功** ({new_success_count}): {format_word_preview(new_summary['added'])}\n\n"
    desp += (
        f"**本次新增跳过重复** ({skipped_count}): "
        f"{format_word_preview(new_summary['skipped_duplicate'])}\n\n"
    )
    desp += (
        f"**本次新增最终失败** ({new_failure_count}): "
        f"{format_word_preview(new_summary['retryable_failed'])}\n\n"
    )
    desp += (
        f"**失败队列总数** ({len(final_failed_queue)}): "
        f"{format_word_preview([word.uuid for word in final_failed_queue])}\n\n"
    )
    desp += f"**执行时间**: {end_time - start_time}\n"
    sc_send(title, desp)


if __name__ == "__main__":
    import sys

    configure_logging()

    if "--daemon" in sys.argv:
        logger.info("启动守护进程模式 (每 %s 小时执行一次)...", config.SYNC_INTERVAL_HOURS)
        schedule.every(config.SYNC_INTERVAL_HOURS).hours.do(job)
        job()
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        job()
