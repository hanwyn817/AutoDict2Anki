import requests
import json
# from config import ANKI_DECK_NAME, ANKI_WEB_COOKIE

def can_add_card(target_word, target_deck_name):
    url = "http://127.0.0.1:8765"  # AnkiConnect的默认地址
    headers = {'Content-Type': 'application/json'}

    note = {
        "action": "canAddNotes",
        "version": 6,
        "params": {
            "notes": [
                {
                    "deckName": target_deck_name,
                    "modelName": "基础",
                    "fields": {
                        "正面": target_word,
                        "背面": ""
                    },
                "tags": []
                }
            ]
        }
    }

    response = requests.post(url, data=json.dumps(note), headers=headers, timeout=5)

    if response.status_code == 200:
        print(json.loads(response.text))
        return json.loads(response.text)["result"][0] #可以添加卡片时应返回Ture
    else:
        print("Error: Failed to response from AnkiConnect.")
        return False

def add_card_to_anki_by_ankiConnect(front, back, deck_name):
    """
    通过AnkiConnect将单词卡片添加到Anki中
    """
    url = "http://127.0.0.1:8765"  # AnkiConnect的默认地址
    headers = {'Content-Type': 'application/json'}

    note = {
        "action": "addNote",
        "version": 6,
        "params": {
            "note": {
                "deckName": deck_name,
                "modelName": "基础",
                "fields": {
                    "正面": front,
                    "背面": back
                },
                "options": {
                    "allowDuplicate": False,
                    "duplicateScope": "deck",
                },
                "tags": []
            }
        }
    }


    response = requests.post(url, data=json.dumps(note), headers=headers, timeout=5)

    if response.status_code == 200:
        # print(f"Connected to Anki and received response while adding '{front}'")
        return json.loads(response.text)
    else:
        print("Error: Failed to response from AnkiConnect.")


# def add_card_to_anki_by_post(front, back):
#     """
#         通过AnkiWeb的POST方法将单词卡片添加到Anki中
#     """
#     # 目标URL
#     url = "https://ankiuser.net/svc/editor/add-or-update"
#
#     # 请求头部信息
#     headers = {
#         "Accept": "*/*",
#         "Content-Type": "application/octet-stream",
#         "Origin": "https://ankiuser.net",
#         "Referer": "https://ankiuser.net/add",
#         "Sec-Ch-Ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
#         "Sec-Ch-Ua-Platform": '"Windows"',
#         "Sec-Fetch-Dest": "empty",
#         "Sec-Fetch-Mode": "cors",
#         "Sec-Fetch-Site": "same-origin",
#         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
#         "Cookie": ANKI_WEB_COOKIE
#     }
#
#     # 请求体数据
#     data = b""  # 这个是空的，根据需要修改
#
#     # 发送 POST 请求
#     response = requests.post(url, headers=headers, data=data)
#     if response.status_code == 200:
#         print(f"请求成功: {response.status_code}")
#     else:
#         print(f"请求失败: {response.status_code}")
