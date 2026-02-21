import json
import os
import logging
from jinja2 import Environment, FileSystemLoader

from http_utils import request_with_retry
import config

logger = logging.getLogger(__name__)

AI_TIMEOUT = 20
AI_MAX_RETRIES = 3

def get_sys_prompt():
    return f"""
你是一名专业的{config.USER_TARGET_EXAM}英语教师。现在我会给你一个英文单词或词组，你需要返回它的详细中文释义和例句，要求如下：

1. 输出必须为严格的 JSON 格式，并且没有除 JSON 字符串之外的字符。结构为：
{{
  "word": "单词",
  "meanings": [
    {{
      "meaning": "中文含义",
      "examples": [
        {{
          "english": "英文例句",
          "translation": "中文翻译"
        }},
        {{
          "english": "英文例句",
          "translation": "中文翻译"
        }}
      ]
    }}
  ]
}}

2. 对于该单词或词组的每个常见中文含义，都必须单独列出一个 `meaning` 条目。  
   - 如果该词有多个常用含义，请全部列出。  
   - 每个含义必须提供**至少两个**不同的英文例句，例句中可以使用该词的不同词形变化（如时态、复数等）。

3. 例句要求：  
   - 简洁自然，语法正确，贴近{config.USER_TARGET_EXAM}考试场景或常见英文表达。  
   - 例句必须与对应的中文含义高度匹配，避免含糊不清或生僻用法。  
   - 提供的中文翻译需准确且流畅。

4. 即使你无法确定某个含义，也必须保持 JSON 结构完整，但可将 `meaning` 标注为 "未知含义"。

现在我要查询的单词是：
"""

def get_word_data_ai(word, api_key):
    if not api_key:
        raise ValueError("AI_API_KEY 未配置，无法调用 AI 释义服务。")

    query_prompt = get_sys_prompt() + word
    url = config.AI_API_URL
    payload = {
        "model": config.AI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": query_prompt,
            }
        ],
        "stream": False,
        "max_tokens": 1024,
        "stop": ["null"],
        "temperature": 0.7,
        "top_p": 0.7,
        "top_k": 50,
        "frequency_penalty": 0.5,
        "n": 1,
        "response_format": {"type": "text"}
    }
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }

    response = request_with_retry(
        "POST",
        url,
        json=payload,
        headers=headers,
        timeout=AI_TIMEOUT,
        max_retries=AI_MAX_RETRIES,
    )
    response.raise_for_status()
    return response.text

def formatted_word_data(word, api_key):
    # 提取 content 的内容
    word_json_data = get_word_data_ai(word, api_key)
    word_json_data = json.loads(word_json_data)["choices"][0]["message"]["content"]
    # 去除 content 中的 Markdown 代码块标记（```json 和 ```）
    word_json_data = word_json_data.strip()
    if word_json_data.startswith("```json"):
        word_json_data = word_json_data[len("```json"):].strip()
    if word_json_data.startswith("```"):
        word_json_data = word_json_data[len("```"):].strip()
    if word_json_data.endswith("```"):
        word_json_data = word_json_data[:-len("```")].strip()
    # 将 content 中的 JSON 字符串解析为 Python 字典
    word_json_data = json.loads(word_json_data)

    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('word_card.html')

    # 异常处理函数，验证JSON格式
    def validate_json(data):
        if not isinstance(data, dict):
            raise ValueError("JSON数据必须是一个字典格式。")

        if "word" not in data or "meanings" not in data:
            raise KeyError('缺少必需的字段："word" 或 "meanings"')

        if not isinstance(data["meanings"], list):
            raise TypeError('字段 "meanings" 必须是一个列表。')

        for meaning in data["meanings"]:
            if "meaning" not in meaning or "examples" not in meaning:
                raise KeyError('每个含义必须包含 "meaning" 和 "examples" 字段。')
            if not isinstance(meaning["examples"], list):
                raise TypeError('字段 "examples" 必须是一个列表。')
            for example in meaning["examples"]:
                if "english" not in example or "translation" not in example:
                    raise KeyError('每个例句必须包含 "english" 和 "translation" 字段。')

    try:
        # 验证返回的JSON数据结构是否符合预期
        validate_json(word_json_data)

        # 将模型返回的数据插入到模板中
        html_content = template.render(
            word=word_json_data["word"],
            meanings=word_json_data["meanings"]
        )
        return html_content

    except ValueError as ve:
        logger.error("AI 数据格式错误: %s", ve)
        return ""
    except KeyError as ke:
        logger.error("AI 数据缺少字段: %s", ke)
        return ""
    except TypeError as te:
        logger.error("AI 数据类型错误: %s", te)
        return ""
    except Exception as e:
        logger.error("AI 释义处理未知错误: %s", e)
        return ""
