import os
from dotenv import load_dotenv

load_dotenv()


def _get_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数，当前值为: {raw_value}") from exc

    if value <= 0:
        raise ValueError(f"{name} 必须大于 0，当前值为: {raw_value}")

    return value

# 词典配置
MDX_FILE_PATH = os.environ.get("MDX_FILE_PATH", "resources/Collins COBUILD (CN).mdx")
MDD_FILE_PATH = os.environ.get("MDD_FILE_PATH", "resources/Collins COBUILD (CN).mdd")
DATA_DIR = os.environ.get("DATA_DIR", ".")
CURSOR_FILE_PATH = os.environ.get("CURSOR_FILE_PATH", os.path.join(DATA_DIR, "last_run_time.txt"))
FAILED_QUEUE_FILE_PATH = os.environ.get(
    "FAILED_QUEUE_FILE_PATH",
    os.path.join(DATA_DIR, "failed_words_queue.json"),
)
RESULT_FILE_PATH = os.environ.get("RESULT_FILE_PATH", os.path.join(DATA_DIR, "result.txt"))
INITIAL_CURSOR_TIME = os.environ.get("INITIAL_CURSOR_TIME", "").strip()
SYNC_INTERVAL_HOURS = _get_int_env("SYNC_INTERVAL_HOURS", 12)

# Anki 配置
ANKI_SYNC_METHOD = os.environ.get("ANKI_SYNC_METHOD", "ankiconnect").lower() # 'ankiconnect' or 'ankiweb'
ANKI_CONNECT_URL = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
ANKI_DECK_NAME = os.environ.get("ANKI_DECK_NAME", "Manki's Daily")
ANKI_NOTE_TYPE = os.environ.get("ANKI_NOTE_TYPE", "基础")
ANKIWEB_COOKIE = os.environ.get("ANKIWEB_COOKIE", "") or os.environ.get("ANKI_WEB_COOKIE", "")

# AI 配置
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_API_URL = os.environ.get("AI_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
AI_MODEL = os.environ.get("AI_MODEL", "Pro/deepseek-ai/DeepSeek-V3")
USER_TARGET_EXAM = os.environ.get("USER_TARGET_EXAM", "雅思")

# 推送配置
SERVERCHAN_SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

