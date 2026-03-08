import os
from dotenv import load_dotenv

load_dotenv()

# 词典配置
MDX_FILE_PATH = os.environ.get("MDX_FILE_PATH", "resources/Collins COBUILD (CN).mdx")
MDD_FILE_PATH = os.environ.get("MDD_FILE_PATH", "resources/Collins COBUILD (CN).mdd")

# Anki 配置
ANKI_SYNC_METHOD = os.environ.get("ANKI_SYNC_METHOD", "ankiconnect").lower() # 'ankiconnect' or 'ankiweb'
ANKI_CONNECT_URL = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
ANKI_DECK_NAME = os.environ.get("ANKI_DECK_NAME", "Manki's Daily")
ANKIWEB_COOKIE = os.environ.get("ANKIWEB_COOKIE", "") or os.environ.get("ANKI_WEB_COOKIE", "")

# AI 配置
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_API_URL = os.environ.get("AI_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
AI_MODEL = os.environ.get("AI_MODEL", "Pro/deepseek-ai/DeepSeek-V3")
USER_TARGET_EXAM = os.environ.get("USER_TARGET_EXAM", "雅思")
