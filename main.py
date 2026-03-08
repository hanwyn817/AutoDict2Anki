import datetime
import json
import logging
import os
import schedule
import time
from typing import Dict, List, Optional, Tuple

import requests

import config
from ai import formatted_word_data
from anki import add_card_to_anki_by_ankiConnect, can_add_card
from anki_web import add_card_to_ankiweb
from datetime_utils import format_datetime_for_storage, parse_datetime_flexible
from eudict_fetcher import get_all_words_data, is_cookie_valid
from mdx_dict import get_word_definition
from models import ProcessResult, WordEntry

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CURSOR_FILE_PATH = "last_run_time.txt"


def get_valid_cookie(initial_cookie: Optional[str]) -> Optional[str]:
    cookie = initial_cookie or ""
    if is_cookie_valid(cookie):
        return cookie

    logger.error("当前 cookie 无效或已过期，请运行 `python login.py` 更新 Cookie。程序终止。")
    return None


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


def process_word(word: WordEntry, deck_name: str) -> ProcessResult:
    """获取单词定义并添加到 Anki。"""
    try:
        definition = get_word_definition(word.uuid, config.MDX_FILE_PATH)
    except FileNotFoundError as exc:
        logger.error("MDX 文件不存在: %s", exc)
        return ProcessResult(status="failed", word=word.uuid, reason=str(exc))
    except Exception as exc:
        logger.error("词典查询失败，word=%s, error=%s", word.uuid, exc)
        return ProcessResult(status="failed", word=word.uuid, reason=f"词典查询失败: {exc}")

    if not definition:
        try:
            definition = formatted_word_data(word.uuid, config.AI_API_KEY)
        except Exception as exc:
            logger.error("AI 释义失败，word=%s, error=%s", word.uuid, exc)
            return ProcessResult(status="failed", word=word.uuid, reason=f"AI 释义失败: {exc}")

    if not definition:
        return ProcessResult(status="failed", word=word.uuid, reason="无法获取到释义")

    try:
        if config.ANKI_SYNC_METHOD == "ankiweb":
            add_result = add_card_to_ankiweb(word.uuid, definition, deck_name)
        else:
            add_result = add_card_to_anki_by_ankiConnect(word.uuid, definition, deck_name)
    except requests.exceptions.ConnectionError:
        # AnkiConnect 未连接，向上抛出以阻止后续流程
        raise
    except Exception as exc:
        logger.error("写入 Anki 失败，word=%s, error=%s", word.uuid, exc)
        return ProcessResult(status="failed", word=word.uuid, reason=f"写入 Anki 失败: {exc}")

    add_error = add_result.get("error") if isinstance(add_result, dict) else "Anki 返回格式错误"
    if not add_error:
        logger.info("Added word %s to Anki successfully.", word.uuid)
        return ProcessResult(status="added", word=word.uuid)
    return ProcessResult(status="failed", word=word.uuid, reason=str(add_error))


def get_new_words_list(last_run_cursor: Tuple[datetime.datetime, Optional[str]]) -> List[WordEntry]:
    """根据游标获取新增单词列表。"""
    last_run_time, last_run_uuid = last_run_cursor
    cookie = get_valid_cookie(os.environ.get("EUDICT_WEB_COOKIE"))
    if not cookie:
        return []

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


def process_words(new_words: List[WordEntry], deck_name: str) -> List[ProcessResult]:
    """处理单词并返回处理结果列表。"""
    results: List[ProcessResult] = []
    
    use_ankiweb = config.ANKI_SYNC_METHOD == "ankiweb"

    for word in new_words:
        try:
            can_add = True
            if not use_ankiweb:
                can_add = can_add_card(word.uuid, deck_name)

            if can_add:
                results.append(process_word(word, deck_name))
            else:
                results.append(
                    ProcessResult(
                        status="skipped_duplicate",
                        word=word.uuid,
                        reason=f"牌组 {deck_name} 中已存在",
                    )
                )
        except requests.exceptions.ConnectionError:
            raise
        except Exception as exc:
            logger.error("处理单词失败，word=%s, error=%s", word.uuid, exc)
            results.append(ProcessResult(status="failed", word=word.uuid, reason=str(exc)))
    return results


def get_progress_cursor_word(
    new_words: List[WordEntry],
    results: List[ProcessResult],
) -> Optional[WordEntry]:
    progressed_word: Optional[WordEntry] = None
    for word, result in zip(new_words, results):
        if result.status == "failed":
            break
        progressed_word = word
    return progressed_word


def summarize_results(results: List[ProcessResult]) -> Dict[str, List[str]]:
    summary: Dict[str, List[str]] = {
        "added": [],
        "skipped_duplicate": [],
        "failed": [],
    }
    
    skipped_groups = {}

    for result in results:
        if result.status == "added":
            summary["added"].append(result.word)
            continue
        if result.status == "skipped_duplicate":
            reason = result.reason or "未知牌组"
            if reason not in skipped_groups:
                skipped_groups[reason] = []
            skipped_groups[reason].append(result.word)
            continue

        detail = result.word
        if result.reason:
            detail = f"{result.word}: {result.reason}"
        summary["failed"].append(detail)

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
    results: List[ProcessResult],
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    deck_name: str,
    result_file_path: str = "result.txt",
) -> None:
    """写入结果到文件并输出日志。"""
    summary = summarize_results(results)
    success_count = sum(1 for r in results if r.status == "added")
    skipped_count = sum(1 for r in results if r.status == "skipped_duplicate")
    failure_count = sum(1 for r in results if r.status == "failed")

    logger.info("Job completed. Successfully processed %s words.", success_count)
    logger.info("Skipped duplicate words: %s", skipped_count)
    logger.info("Failed words: %s", failure_count)
    if skipped_count > 0:
        logger.warning(
            "Skipped words: %s",
            summary["skipped_duplicate"][0] if summary["skipped_duplicate"] else "",
        )
    if failure_count > 0:
        logger.warning("Failed words: %s", ", ".join(summary["failed"]))
    logger.info("Job completed at %s", end_time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Execution time: %s", end_time - start_time)
    logger.info("运行结果已保存至 %s", result_file_path)

    with open(result_file_path, "w", encoding="utf-8") as f:
        f.write(f"目标牌组: {deck_name}\n")
        f.write(f"成功单词: {success_count}\n")
        f.write(f"跳过重复: {skipped_count}\n")
        f.write(f"失败单词: {failure_count}\n")
        f.write(f"成功单词列表: {', '.join(summary['added'])}\n")
        f.write(
            f"跳过单词列表: {summary['skipped_duplicate'][0] if summary['skipped_duplicate'] else ''}\n"
        )
        f.write(f"失败单词列表: {', '.join(summary['failed'])}\n")
        f.write(f"执行时间: {end_time - start_time}\n")


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
    with open(CURSOR_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))


def job() -> None:
    job_success = False
    try:
        last_sync_cursor = get_last_sync_cursor()
    except Exception:
        print("last_run_time.txt 中的游标格式不正确，请修正后重试。")
        return

    if not last_sync_cursor:
        print("未获取到上次运行时间，请手动填写 last_run_time.txt 后再运行程序。")
        return

    last_run_time_dt, last_run_uuid = last_sync_cursor
    if last_run_time_dt > datetime.datetime.now():
        print("last_run_time.txt 中的时间晚于当前时间，请检查并修正。")
        return

    logger.info(
        "上次运行游标: time=%s uuid=%s",
        format_datetime_for_storage(last_run_time_dt),
        last_run_uuid or "",
    )
    start_time = datetime.datetime.now()
    try:
        new_words = get_new_words_list(last_sync_cursor)
        if not new_words:
            logger.warning("未获取到自上次运行时间以来的新单词，任务终止。")
            return
        results = process_words(new_words, config.ANKI_DECK_NAME)
        job_success = True
    except requests.exceptions.ConnectionError:
        logger.error("连接 AnkiConnect 失败，请确认 Anki 已启动且插件可用。")
        return
    except Exception as exc:
        logger.error("Error fetching new words: %s", exc)
        return

    end_time = datetime.datetime.now()
    if job_success:
        progress_word = get_progress_cursor_word(new_words, results)
        if progress_word:
            set_last_sync_cursor(progress_word.addtime, progress_word.uuid)
            logger.info(
                "游标已推进到: time=%s uuid=%s",
                format_datetime_for_storage(progress_word.addtime),
                progress_word.uuid,
            )
        else:
            logger.warning("本次无可推进游标的成功处理记录，保留原游标。")
        write_result(results, start_time, end_time, config.ANKI_DECK_NAME)


if __name__ == "__main__":
    import sys
    
    # 检查是否以守护进程模式启动
    if "--daemon" in sys.argv:
        logger.info("启动守护进程模式 (每 12 小时执行一次)...")
        schedule.every(12).hours.do(job)
        
        # 立即执行一次
        job()
        
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        # 单次执行任务
        job()
