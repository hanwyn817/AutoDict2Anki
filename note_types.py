"""制卡流程支持的笔记类型，以及无法使用的原因。"""
import re


class NoteTypes(dict):
    def __init__(self):
        super().__init__()
        self.excluded = {}


def unsupported_reason(name, fields, templates=None):
    if len(fields) != 2:
        return f"有 {len(fields)} 个字段，需要恰好两个字段"
    if templates is not None:
        formats = (str(value) for template in templates.values() for value in template.values())
        if any(re.search(r"{{\s*cloze\s*:", text, re.I) for text in formats):
            return "挖空题模板，不能按单词／释义方式生成卡片"
    else:
        # AnkiWeb 添加页不提供卡片模板；按可见名称和字段用途排除挖空题。
        normalized = [re.sub(r"[\s_-]", "", field).casefold() for field in fields]
        if re.search(r"cloze|挖空|填空", name, re.I) or (
            normalized[0] in ("text", "正文", "文本") and
            normalized[1] in ("backextra", "extra", "背面额外", "额外信息")
        ):
            return "挖空题名称或字段用途，不适合单词／释义制卡"
    return None
