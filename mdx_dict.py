from readmdict import MDX
import os
from typing import Optional

class Dictionary:
    def __init__(self, temp_file_path):
        """
        初始化词典加载类，加载 MDX 文件
        """
        if not os.path.exists(temp_file_path):
            raise FileNotFoundError(f"Error: The MDX file at '{temp_file_path}' does not exist.")

        # 加载 MDX 文件
        self.mdx = MDX(temp_file_path)

    def get_definition(self, word_in_search):
        """
        获取单词的定义
        """
        try:
            # 使用 next 找到第一个 entry 为 word 的元组
            explanation = next(explanation for entry, explanation in self.mdx.items() if entry == word_in_search.encode())
            # 避免css文件不能载入
            recovery_css = '<div class="_collinsEC"><style> @import url(_collinsEC_wrap.css); </style>'
            return recovery_css + explanation.decode('utf-8') + "</div>"
        except StopIteration:
            return None


def get_word_definition(this_word: str, the_file_path: str) -> Optional[str]:
    """
    获取指定单词的定义
    """
    dictionary = Dictionary(the_file_path)
    return dictionary.get_definition(this_word)

# if __name__ == '__main__':
#     word = "sperm"
#     file_path = config.MDX_FILE_PATH  # 配置文件中的词典文件路径
#     print(get_word_definition(word, file_path))
