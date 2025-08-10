import config
import logging
import datetime
import os
from dotenv import load_dotenv
import argparse
from ai import formatted_word_data
from eudict_fetcher import get_all_words_data, is_cookie_valid, get_cookie_via_browser
from mdx_dict import get_word_definition
from anki import add_card_to_anki_by_ankiConnect, can_add_card

# 加载.env文件中的环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("test_main.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def process_word(word, target_deck_name):
    """获取单词定义并添加到Anki"""
    try:
        # 从MDX文件中获取定义
        definition = get_word_definition(word['uuid'], config.MDX_FILE_PATH)

        # 如果没有定义，则使用AI获取
        if definition == "No definition available.":
            definition = formatted_word_data(word['uuid'], os.environ.get("AI_API_KEY", os.environ.get("AI_API_KEY")))

        if definition:
            # 将单词和定义添加到Anki
            add_result = add_card_to_anki_by_ankiConnect(word['uuid'], definition, target_deck_name)
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


def get_recent_words_list(cookie, count=10):
    """获取最近新增的指定数量单词列表"""
    if not is_cookie_valid(cookie):
        logger.warning("当前 cookie 无效，尝试通过浏览器手动登录获取新的 cookie...")
        new_cookie = get_cookie_via_browser()
        if new_cookie:
            cookie = new_cookie
        else:
            logger.error("获取新的 cookie 失败，程序终止。")
            return []
    # 获取所有单词（获取比需要的数量稍多一些，以确保排序后能取到最新的）
    all_words_data = get_all_words_data(cookie, start=0, length=count*2)
    
    # 检查是否有获取到数据
    if not all_words_data:
        logger.warning("未能从欧路词典获取到单词数据")
        return []
    
    # 按添加时间排序，取最新的count个单词
    try:
        sorted_words = sorted(all_words_data, key=lambda x: datetime.datetime.fromisoformat(x['addtime']), reverse=True)
        recent_words_data = sorted_words[:count]
        logger.info(f"成功获取到 {len(recent_words_data)} 个最近新增的单词")
        return recent_words_data
    except Exception as e:
        logger.error(f"排序单词数据时出错: {e}")
        return []


def process_words(new_words, target_deck_name):
    """处理单词，返回成功和失败的单词列表"""
    success_count = 0
    failure_count = 0
    failed_words = []
    succeed_words = []
    for word in new_words:
        # 先判断牌组中是否已有word对应的note，若有则跳过
        if can_add_card(word["uuid"], target_deck_name):
            success, outcome = process_word(word, target_deck_name)
        else:
            success = False
            outcome = f"\n【重复】牌组 {target_deck_name} 中已存在{word['uuid']}，添加失败"
        if success:
            success_count += 1
            succeed_words.append(outcome)
        else:
            failure_count += 1
            failed_words.append(outcome)
    return success_count, failure_count, succeed_words, failed_words


def write_result(success_count, failure_count, succeed_words, failed_words, start_time, end_time, target_deck_name):
    """写入结果到文件并输出日志"""
    logger.info(f"Job completed. Successfully processed {success_count} words: {', '.join(succeed_words)}")
    logger.info(f"Failed to process {failure_count} words.")
    if failure_count > 0:
        logger.warning(f"Failed words: {', '.join(failed_words)}")
    logger.info(f"Job completed at {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Execution time: {end_time - start_time}")
    logger.info(f"运行结果已保存至result.txt")
    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(f"目标牌组: {target_deck_name}\n")
        f.write(f"成功单词: {success_count}\n")
        f.write(f"失败单词: {failure_count}\n")
        f.write(f"成功单词列表: {', '.join(succeed_words)}\n")
        f.write(f"失败单词列表: {', '.join(failed_words)}\n")
        f.write(f"执行时间: {end_time - start_time}\n")


def test_job(target_deck_name):
    """测试任务函数"""
    # 从环境变量获取cookie
    cookie = os.environ.get("EUDICT_WEB_COOKIE")
    if not cookie:
        logger.error("未获取到欧路词典cookie，请检查环境变量配置。")
        return
    
    logger.info(f"开始执行测试任务，目标牌组: {target_deck_name}")
    start_time = datetime.datetime.now()  # 获取开始时间
    try:
        new_words = get_recent_words_list(cookie, count=10)
        if not new_words:
            logger.warning("未获取到最近新增的单词，任务终止。")
            return
        logger.info(f"获取到 {len(new_words)} 个最近新增的单词")
        success_count, failure_count, succeed_words, failed_words = process_words(new_words, target_deck_name)
    except Exception as e:
        logger.error(f"处理单词时出错: {e}")
        success_count = 0
        failure_count = 0
        succeed_words = []
        failed_words = []
    end_time = datetime.datetime.now()  # 获取结束时间
    write_result(success_count, failure_count, succeed_words, failed_words, start_time, end_time, target_deck_name)


if __name__ == "__main__":
    # 创建参数解析器
    parser = argparse.ArgumentParser(description="测试AutoDict2Anki功能")
    parser.add_argument("-d", "--deck", help="目标Anki牌组名称", default="AutoDict_Default")
    parser.add_argument("-c", "--count", type=int, help="获取单词数量", default=10)
    args = parser.parse_args()
    
    target_deck = args.deck
    word_count = args.count
    
    print(f"目标牌组: {target_deck}")
    print(f"获取单词数量: {word_count}")
    print("开始执行测试任务...")
    
    # 执行测试任务
    test_job(target_deck)