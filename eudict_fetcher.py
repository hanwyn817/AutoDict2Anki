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
