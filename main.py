import schedule
import time
import config
import logging
import datetime
import os
from dotenv import load_dotenv
from ai import formatted_word_data
from eudict_fetcher import get_all_words_data, is_cookie_valid, get_cookie_via_browser
from mdx_dict import get_word_definition
from anki import add_card_to_anki_by_ankiConnect, can_add_card

# 读取 .env 中的环境变量（如 Cookie、API Key 等）
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def process_word(word):
    """获取单词定义并添加到Anki"""
    try:
        # 从MDX文件中获取定义
        definition = get_word_definition(word['uuid'], config.MDX_FILE_PATH)

        # 如果没有定义，则使用AI获取
        if definition == "No definition available.":
            definition = formatted_word_data(word['uuid'], os.environ.get("AI_API_KEY", os.environ.get("AI_API_KEY")))

        if definition:
            # 将单词和定义添加到Anki
            add_result = add_card_to_anki_by_ankiConnect(word['uuid'], definition, config.ANKI_DECK_NAME)
            if add_result["error"] is None:
                logger.info(f"Added word {word['uuid']} to Anki successfully.")
                return True, word['uuid']
            else:
                return False, "\n" + word['uuid'] + " " + add_result["error"]
        else:
            return False, word['uuid'] + "无法获取到释义。"  # 返回失败标志和失败单词的uuid
    except Exception as e:
        logger.error(f"Error processing word {word['uuid']}: {e}")
        return False, word['uuid']  # 返回失败标志和失败单词的uuid


def get_new_words_list(last_run_time):
    """获取新增单词列表"""
    cookie = os.environ.get("EUDICT_WEB_COOKIE", os.environ.get("EUDICT_WEB_COOKIE"))
    if not is_cookie_valid(cookie):
        print("当前 cookie 无效，尝试通过浏览器手动登录获取新的 cookie...")
        new_cookie = get_cookie_via_browser()
        if new_cookie:
            cookie = new_cookie
        else:
            print("获取新的 cookie 失败，程序终止。")
            return []
    # 获取所有单词
    all_words_data = get_all_words_data(cookie)
    # 获取自上次运行时间以来的新单词
    last_run_time_dt = datetime.datetime.fromisoformat(last_run_time)
    recent_words_data = [
        entry for entry in all_words_data
        if datetime.datetime.fromisoformat(entry['addtime']) > last_run_time_dt
    ]
    return recent_words_data


def process_words(new_words):
    """处理单词，返回成功和失败的单词列表"""
    success_count = 0
    failure_count = 0
    failed_words = []
    succeed_words = []
    for word in new_words:
        # 先判断牌组中是否已有word对应的note，若有则跳过
        if can_add_card(word["uuid"], config.ANKI_DECK_NAME):
            success, outcome = process_word(word)
        else:
            success = False
            outcome = f"\n【重复】牌组 {config.ANKI_DECK_NAME} 中已存在{word['uuid']}，添加失败"
        if success:
            success_count += 1
            succeed_words.append(outcome)
        else:
            failure_count += 1
            failed_words.append(outcome)
    return success_count, failure_count, succeed_words, failed_words


def write_result(success_count, failure_count, succeed_words, failed_words, start_time, end_time):
    """写入结果到文件并输出日志"""
    logger.info(f"Job completed. Successfully processed {success_count} words: {', ' .join(succeed_words)}")
    logger.info(f"Failed to process {failure_count} words.")
    if failure_count > 0:
        logger.warning(f"Failed words: {', '.join(failed_words)}")
    logger.info(f"Job completed at {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Execution time: {end_time - start_time}")
    logger.info(f"运行结果已保存至result.txt")
    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(f"成功单词: {success_count}\n")
        f.write(f"失败单词: {failure_count}\n")
        f.write(f"成功单词列表: {', '.join(succeed_words)}\n")
        f.write(f"失败单词列表: {', '.join(failed_words)}\n")
        f.write(f"执行时间: {end_time - start_time}\n")


def get_last_run_time():
    try:
        with open("last_run_time.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

def set_last_run_time(run_time):
    with open("last_run_time.txt", "w", encoding="utf-8") as f:
        f.write(run_time.strftime("%Y-%m-%d %H:%M:%S"))


def job():
    last_run_time = get_last_run_time()
    if not last_run_time:
        print("未获取到上次运行时间，请手动填写 last_run_time.txt 后再运行程序。")
        return
    try:
        last_run_time_dt = datetime.datetime.fromisoformat(last_run_time)
    except Exception:
        print("last_run_time.txt 中的时间格式不正确，请手动修正为形如 2025-01-01 20:00:00 的格式。");
        return
    if last_run_time_dt > datetime.datetime.now():
        print("last_run_time.txt 中的时间晚于当前时间，请检查并修正。");
        return
    logger.info(f"上次运行时间: {last_run_time}")
    start_time = datetime.datetime.now()  # 获取开始时间
    try:
        new_words = get_new_words_list(last_run_time)
        if not new_words:
            logger.warning("未获取到自上次运行时间以来的新单词，任务终止。")
            return
        success_count, failure_count, succeed_words, failed_words = process_words(new_words)
    except Exception as e:
        logger.error(f"Error fetching new words: {e}")
        success_count = 0
        failure_count = 0
        succeed_words = []
        failed_words = []
    end_time = datetime.datetime.now()  # 获取结束时间
    set_last_run_time(end_time)
    write_result(success_count, failure_count, succeed_words, failed_words, start_time, end_time)


if __name__ == "__main__":
    # 立即执行 job()，如果是直接运行脚本
    job()

    # 设置定时任务，每天固定时间执行
    # schedule.every().day.at("03:00").do(job)

    # 定时执行任务
    # while True:
    #     schedule.run_pending()
    #     time.sleep(1)
