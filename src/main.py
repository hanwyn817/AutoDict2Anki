import logging
import datetime
import os
from ai import formatted_word_data
from eudict_fetcher import get_new_words, is_cookie_valid, get_cookie_via_browser
from mdx_dict import get_word_definition
from anki import add_card_to_anki_by_ankiConnect,can_add_card

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def process_word(word):
    """获取单词定义并添加到Anki"""
    try:
        # 从MDX文件中获取定义
        definition = get_word_definition(word['uuid'], "resources/Collins COBUILD (CN).mdx")

        # 如果没有定义，则使用AI获取
        if definition == "No definition available.":
            definition = formatted_word_data(word['uuid'], os.environ.get("AI_API_KEY"))

        if definition:
            # 将单词和定义添加到Anki
            add_result = add_card_to_anki_by_ankiConnect(word['uuid'], definition, os.environ.get("ANKI_DECK_NAME", "AutoDict_Default"))
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


def lambda_handler(event, context):
    start_time = datetime.datetime.now()  # 获取开始时间
    logger.info(f"Job started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    success_count = 0
    failure_count = 0
    failed_words = []
    succeed_words=[]

    try:
        # 获取新增单词
        cookie = os.environ.get("EUDICT_WEB_COOKIE")
        if not is_cookie_valid(cookie):
            print("当前 cookie 无效，尝试通过浏览器手动登录获取新的 cookie...")
            new_cookie = get_cookie_via_browser()
            if new_cookie:
                cookie = new_cookie
            else:
                print("获取新的 cookie 失败，程序终止。")
                return

        # 获取新增单词
        new_words = get_new_words(cookie, int(os.environ.get("NEW_WORDS_PERIOD", 1)))

        # 逐个处理每个单词
        for word in new_words:
            # 先判断牌组中是否已有word对应的note，若有则跳过
            if can_add_card(word["uuid"], os.environ.get("ANKI_DECK_NAME", "AutoDict_Default")):
                success, outcome = process_word(word)
            else:
                success = False
                outcome = f"\n【重复】牌组 {os.environ.get("ANKI_DECK_NAME", "AutoDict_Default")} 中已存在与 {word["uuid"]} 相同的note，添加失败。"

            if success:
                success_count += 1
                succeed_words.append(outcome)
            else:
                failure_count += 1
                failed_words.append(outcome)

        # 输出统计结果
        logger.info(f"Job completed. Successfully processed {success_count} words: {', ' .join(succeed_words)}")
        logger.info(f"Failed to process {failure_count} words.")
        if failure_count > 0:
            logger.warning(f"Failed words: {', '.join(failed_words)}")

    except Exception as e:
        logger.error(f"Error fetching new words: {e}")

    end_time = datetime.datetime.now()  # 获取结束时间
    logger.info(f"Job completed at {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Execution time: {end_time - start_time}")


if __name__ == "__main__":
    lambda_handler(event=1, context=1)
