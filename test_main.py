import argparse
import datetime
import logging
import os

from dotenv import load_dotenv

from eudict_fetcher import is_cookie_valid
from login import get_cookie_via_browser
from main import get_recent_words_list, process_words, write_result

# 加载 .env 文件中的环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("test_main.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def run_job(target_deck_name: str, count: int) -> None:
    """测试任务函数。"""
    cookie = os.environ.get("EUDICT_WEB_COOKIE")
    if not cookie:
        logger.error("未获取到欧路词典 cookie，请检查环境变量配置。")
        return

    if not is_cookie_valid(cookie):
        logger.warning("当前 cookie 无效，尝试通过浏览器手动登录获取新的 cookie...")
        new_cookie = get_cookie_via_browser()
        if not new_cookie:
            logger.error("获取新的 cookie 失败，程序终止。")
            return
        cookie = new_cookie

    logger.info("开始执行测试任务，目标牌组: %s", target_deck_name)
    start_time = datetime.datetime.now()

    try:
        new_words = get_recent_words_list(cookie, count=count)
        if not new_words:
            logger.warning("未获取到最近新增的单词，任务终止。")
            return
        logger.info("获取到 %s 个最近新增的单词", len(new_words))
        results = process_words(new_words, target_deck_name)
    except Exception as exc:
        logger.error("处理单词时出错: %s", exc)
        results = []

    end_time = datetime.datetime.now()
    write_result(results, start_time, end_time, target_deck_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试 AutoDict2Anki 功能")
    parser.add_argument("-d", "--deck", help="目标 Anki 牌组名称", default="AutoDict_Default")
    parser.add_argument("-c", "--count", type=int, help="获取单词数量", default=10)
    args = parser.parse_args()

    target_deck = args.deck
    word_count = args.count

    print(f"目标牌组: {target_deck}")
    print(f"获取单词数量: {word_count}")
    print("开始执行测试任务...")

    run_job(target_deck, word_count)
