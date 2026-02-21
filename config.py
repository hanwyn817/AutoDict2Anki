import os

# 词典配置
MDX_FILE_PATH = os.environ.get("MDX_FILE_PATH", "resources/Collins COBUILD (CN).mdx")
MDD_FILE_PATH = os.environ.get("MDD_FILE_PATH", "resources/Collins COBUILD (CN).mdd")

# Anki 配置
ANKI_CONNECT_URL = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
ANKI_DECK_NAME = os.environ.get("ANKI_DECK_NAME", "Manki's Daily")

# AI 配置
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_API_URL = os.environ.get("AI_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
AI_MODEL = os.environ.get("AI_MODEL", "Pro/deepseek-ai/DeepSeek-V3")
USER_TARGET_EXAM = os.environ.get("USER_TARGET_EXAM", "雅思")
