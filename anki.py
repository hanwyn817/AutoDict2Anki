import json
from typing import Any, Dict

from http_utils import request_with_retry
import config
from note_types import NoteTypes, unsupported_reason
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
        request_label="AnkiConnect",
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
                    "modelName": config.ANKI_NOTE_TYPE,
                    "fields": {
                        config.ANKI_FRONT_FIELD: target_word,
                        config.ANKI_BACK_FIELD: "",
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
                "modelName": config.ANKI_NOTE_TYPE,
                "fields": {
                    config.ANKI_FRONT_FIELD: front,
                    config.ANKI_BACK_FIELD: back,
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


def invoke(action, **params):
    response = _invoke_anki_connect({"action": action, "version": 6, "params": params})
    if response.get("error") is not None:
        raise RuntimeError(f"AnkiConnect {action} 失败: {response['error']}")
    return response.get("result")


def get_catalog():
    """读取牌组和可映射的双字段笔记类型，不写入 Anki。"""
    decks = invoke("deckNames")
    models = NoteTypes()
    for name in invoke("modelNames"):
        fields = invoke("modelFieldNames", modelName=name)
        templates = invoke("modelTemplates", modelName=name) if len(fields) == 2 else None
        reason = unsupported_reason(name, fields, templates)
        if reason:
            models.excluded[name] = reason
        else:
            models[name] = fields
    return decks, models
