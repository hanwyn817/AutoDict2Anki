"""无凭据的任务配置，以及任务运行期间的配置作用域。"""
import json
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import config


def root():
    return Path(config.DATA_DIR) / "profiles"


def validate_name(name):
    if not re.fullmatch(r"[\w -]{1,80}", name) or not name.strip():
        raise ValueError("配置名称限 1–80 个中文、字母、数字、空格、下划线或连字符")
    return name


@dataclass
class Profile:
    name: str = "default"
    method: str = config.ANKI_SYNC_METHOD
    deck: str = config.ANKI_DECK_NAME
    note_type: str = config.ANKI_NOTE_TYPE
    front_field: str = config.ANKI_FRONT_FIELD
    back_field: str = config.ANKI_BACK_FIELD
    style: str = config.CARD_STYLE
    strategy: str = config.DEFINITION_STRATEGY
    exam: str = config.USER_TARGET_EXAM
    source: str = "incremental"
    count: int = 10
    file_path: str = ""

    def validate(self):
        validate_name(self.name)
        if self.method not in ("ankiconnect", "ankiweb"):
            raise ValueError("不支持的 Anki 写入方式")
        if self.style not in ("current", "simple"):
            raise ValueError("不支持的卡片样式")
        if self.strategy not in ("dictionary_first", "ai_only", "dictionary_only"):
            raise ValueError("不支持的释义策略")
        required = (self.name, self.method, self.deck, self.note_type, self.front_field, self.back_field,
                    self.style, self.strategy, self.exam, self.source)
        if not all(isinstance(v, str) and v.strip() for v in required):
            raise ValueError("任务配置字段不能为空")
        if self.source not in ("incremental", "recent", "manual", "file"):
            raise ValueError("不支持的单词来源")
        if type(self.count) is not int or self.count <= 0:
            raise ValueError("最近单词数量必须是正整数")
        if not isinstance(self.file_path, str):
            raise ValueError("文件路径必须是字符串")
        if self.front_field == self.back_field:
            raise ValueError("正面和背面不能映射到同一字段")

    @property
    def directory(self):
        return root() / validate_name(self.name)

    def save(self):
        self.validate()
        write_json(self.directory / "config.json", asdict(self))

    @classmethod
    def load(cls, name):
        path = root() / validate_name(name) / "config.json"
        profile = cls(**json.loads(path.read_text(encoding="utf-8")))
        profile.validate()
        if profile.name != name:
            raise ValueError("配置名称与目录不一致")
        return profile


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


@contextmanager
def activate(profile):
    """只在当前同步任务内覆盖配置，退出后恢复，包括发生异常时。"""
    if profile is None:
        yield
        return
    import main
    profile.validate()
    values = dict(ANKI_SYNC_METHOD=profile.method, ANKI_DECK_NAME=profile.deck,
                  ANKI_NOTE_TYPE=profile.note_type, ANKI_FRONT_FIELD=profile.front_field,
                  ANKI_BACK_FIELD=profile.back_field, CARD_STYLE=profile.style,
                  DEFINITION_STRATEGY=profile.strategy, USER_TARGET_EXAM=profile.exam)
    paths = {key: str(profile.directory / filename) for key, filename in (
        ("CURSOR_FILE_PATH", "last_run_time.txt"),
        ("FAILED_QUEUE_FILE_PATH", "failed_words_queue.json"),
        ("RESULT_FILE_PATH", "result.txt"))}
    previous = {key: getattr(config, key) for key in dict(values, **paths)}
    previous_main = {key: getattr(main, key) for key in paths}
    try:
        for key, value in dict(values, **paths).items():
            setattr(config, key, value)
        for key, value in paths.items():
            setattr(main, key, value)
        yield
    finally:
        for key, value in previous.items():
            setattr(config, key, value)
        for key, value in previous_main.items():
            setattr(main, key, value)
