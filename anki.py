import json
from typing import Any, Dict

from http_utils import request_with_retry
import config
import datetime

ANKI_CONNECT_URL = config.ANKI_CONNECT_URL
HEADERS = {"Content-Type": "application/json"}


def _invoke_anki_connect(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = request_with_retry(
        "POST",
        ANKI_CONNECT_URL,
        data=json.dumps(payload),
        headers=HEADERS,
        timeout=5,
        max_retries=3,
        backoff_factor=0.2,
        retry_status_codes=(502, 503, 504),
    )
    response.raise_for_status()

    response_data = response.json()
    if not isinstance(response_data, dict):
        raise RuntimeError("AnkiConnect 返回格式错误：响应不是 JSON 对象")
    return response_data


def can_add_card(target_word: str, target_deck_name: str) -> bool:
    payload = {
        "action": "canAddNotes",
        "version": 6,
        "params": {
            "notes": [
                {
                    "deckName": target_deck_name,
                    "modelName": "基础",
                    "fields": {
                        "正面": target_word,
                        "背面": "",
                    },
                    "options": {
                        "allowDuplicate": False,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {
                            "deckName": target_deck_name,
                            "checkChildren": False,
                            "checkAllModels": False,
                        },
                    },
                    "tags": [],
                }
            ]
        },
    }

    response_data = _invoke_anki_connect(payload)
    if response_data.get("error") is not None:
        raise RuntimeError(f"AnkiConnect canAddNotes 失败: {response_data['error']}")

    result = response_data.get("result")
    if not isinstance(result, list) or not result:
        raise RuntimeError("AnkiConnect canAddNotes 返回 result 异常")
    return bool(result[0])


def add_card_to_anki_by_ankiConnect(front: str, back: str, deck_name: str) -> Dict[str, Any]:
    """
    通过 AnkiConnect 将单词卡片添加到 Anki 中。
    """
    payload = {
        "action": "addNote",
        "version": 6,
        "params": {
            "note": {
                "deckName": deck_name,
                "modelName": "基础",
                "fields": {
                    "正面": front,
                    "背面": back,
                },
                "options": {
                    "allowDuplicate": False,
                    "duplicateScope": "deck",
                    "duplicateScopeOptions": {
                        "deckName": deck_name,
                        "checkChildren": False,
                        "checkAllModels": False,
                    },
                },
                "tags": [],
            }
        },
    }

    return _invoke_anki_connect(payload)
