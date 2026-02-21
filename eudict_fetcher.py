import logging
import os
from typing import Any, Dict, List, Optional

import requests

from datetime_utils import parse_datetime_flexible
from http_utils import request_with_retry
from models import WordEntry

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10
HTTP_MAX_RETRIES = 3


def parse_word_entry(raw_word: Dict[str, Any]) -> Optional[WordEntry]:
    uuid = raw_word.get("uuid")
    if not uuid:
        logger.warning("跳过无 uuid 的单词记录: %s", raw_word)
        return None

    parsed_addtime = parse_datetime_flexible(str(raw_word.get("addtime", "")))
    if not parsed_addtime:
        logger.warning("跳过 addtime 无法解析的单词 '%s': %r", uuid, raw_word.get("addtime"))
        return None

    return WordEntry(
        id=raw_word.get("id"),
        uuid=uuid,
        exp=raw_word.get("exp", "") or "",
        addtime=parsed_addtime,
    )


def is_cookie_valid(cookie: str) -> bool:
    """
    通过请求需要登录态的页面检查 cookie 是否有效。
    若响应中包含“自动登录”，认为 cookie 已失效。
    """
    if not cookie:
        return False

    test_url = "https://my.eudic.net"
    headers = {"Cookie": cookie}
    try:
        response = request_with_retry(
            "GET",
            test_url,
            headers=headers,
            timeout=HTTP_TIMEOUT,
            max_retries=HTTP_MAX_RETRIES,
        )
    except requests.exceptions.RequestException as exc:
        logger.error("测试 cookie 时出错: %s", exc)
        return False

    if "自动登录" in response.text:
        logger.warning("检测到响应中包含“自动登录”，cookie 可能已失效。")
        return False
    return response.status_code == 200


def get_cookie_via_browser() -> str:
    """
    通过 Selenium 弹出浏览器，供用户手动登录后获取新的 cookie。
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

    login_url = "https://dict.eudic.net/Account/Login"
    driver.get(login_url)
    print("浏览器已打开，请在浏览器中手动完成登录。")
    print("登录完成后，请在此命令行中按回车继续...")
    input()

    cookies = driver.get_cookies()
    driver.quit()

    if not cookies:
        print("未能在浏览器中获取到任何 cookie。")
        return ""

    cookie_str = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
    print(f"已获取新的 cookie（长度: {len(cookie_str)}）")

    if update_env_cookie(cookie_str):
        print("新 cookie 已保存到 .env 文件")
    else:
        print("警告：未能保存新 cookie 到 .env 文件，请手动更新")
    return cookie_str


def update_env_cookie(new_cookie: str) -> bool:
    """
    更新 .env 文件中的 EUDICT_WEB_COOKIE 变量。
    """
    env_file_path = ".env"
    if not os.path.exists(env_file_path):
        print(f"错误：{env_file_path} 文件不存在")
        return False

    try:
        with open(env_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        cookie_updated = False
        for i, line in enumerate(lines):
            if line.startswith("EUDICT_WEB_COOKIE="):
                lines[i] = f'EUDICT_WEB_COOKIE="{new_cookie}"\n'
                cookie_updated = True
                break

        if not cookie_updated:
            lines.append(f'EUDICT_WEB_COOKIE="{new_cookie}"\n')

        with open(env_file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as exc:
        print(f"更新 .env 文件时出错：{exc}")
        return False


def _build_request_params(start: int, length: int) -> Dict[str, Any]:
    return {
        "=8": "",
        "draw": 2,
        "columns[0][data]": "id",
        "columns[1][data]": "id",
        "columns[2][data]": "word",
        "columns[3][data]": "phon",
        "columns[4][data]": "exp",
        "columns[5][data]": "rating",
        "columns[6][data]": "addtime",
        "start": start,
        "length": length,
        "categoryid": "-1",
    }


def get_all_words_data(cookie: str, page_size: int = 200, max_pages: Optional[int] = None) -> List[WordEntry]:
    """
    分页拉取欧路词典生词本数据，直到空页为止。

    返回:
    - List[WordEntry]: addtime 已解析为 datetime，坏数据会被跳过并记录 warning。
    """
    if not cookie:
        return []
    if page_size <= 0:
        raise ValueError("page_size 必须大于 0")

    url = "https://my.eudic.net/StudyList/WordsDataSource"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": cookie,
    }

    words_list: List[WordEntry] = []
    start = 0
    page_count = 0

    while True:
        if max_pages is not None and page_count >= max_pages:
            break

        params = _build_request_params(start=start, length=page_size)
        response = request_with_retry(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=HTTP_TIMEOUT,
            max_retries=HTTP_MAX_RETRIES,
        )
        response.raise_for_status()

        data = response.json()
        raw_words = data.get("data", [])
        if not isinstance(raw_words, list):
            raise ValueError("欧路返回数据格式错误: data 字段不是列表")

        if not raw_words:
            break

        for raw_word in raw_words:
            if not isinstance(raw_word, dict):
                logger.warning("跳过非字典格式的单词记录: %r", raw_word)
                continue
            parsed_word = parse_word_entry(raw_word)
            if parsed_word:
                words_list.append(parsed_word)

        page_count += 1
        if len(raw_words) < page_size:
            break
        start += page_size

    return words_list
