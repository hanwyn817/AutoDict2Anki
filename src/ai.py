import json
import requests

sys_prompt = """
我是一个雅思英语的学习者，现在正在学习英文单词或者词组。你是一位专业的英语老师，请为我提供单词的中文含义，并为每个含义提供两个英文例句及其中文翻译。例句中的单词可以使用该单词的不同变体形式（如动词的时态、名词的复数等）。请将输出格式化为 JSON，结构应包含以下内容：

- "word": 单词的英文内容
- "meanings": 一个列表，每个元素代表一个中文含义。每个中文含义应包含：
  - "meaning": 中文含义
  - "examples": 一个列表，包含两个例句，每个例句应包含：
    - "english": 英文例句
    - "translation": 英文例句的中文翻译

请确保例句清晰且准确，并确保以此JSON格式返回结果。即使你确实查询不到对应的中文含义，也要按JSON格式返回结构。我需要查询的单词为：
"""

def get_word_data_ai(word, api_key):
    query_prompt = sys_prompt + word
    url = "https://api.siliconflow.cn/v1/chat/completions"
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [
            {
                "role": "user",
                "content": query_prompt,
            }
        ],
        "stream": False,
        "max_tokens": 512,
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

    response = requests.request("POST", url, json=payload, headers=headers)
    # print(response.status_code)
    return response.text

def formatted_word_data(word, api_key):
    # 提取 content 的内容
    word_json_data =get_word_data_ai(word, api_key)
    word_json_data = json.loads(word_json_data)["choices"][0]["message"]["content"]
    # 去除 content 中的 Markdown 代码块标记（```json 和 ```）
    word_json_data = word_json_data.strip("```json\n").strip("```")
    # 将 content 中的 JSON 字符串解析为 Python 字典
    word_json_data = json.loads(word_json_data)


    html_template = """
    <div class="_collinsEC">
        <style>
            @import url(_collinsEC_wrap.css);
        </style>

        <head>
            <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
            <link href="collinsEC.css" rel="stylesheet" type="text/css" />
        </head>

        <body>
            <a name="page_top"></a>

            <div class="C1_word_header">
                <span class="C1_word_header_word">{word}</span>
                <span class="C1_color_bar">
                    <ul>
                        <li class="C1_cabr_1"></li>
                        <li class="C1_cabr_2"></li>
                        <li class="C1_cabr_3"></li>
                        <li class="C1_cabr_4"></li>
                        <li class="C1_cabr_5"></li>
                        <li class="C1_cabr_6"></li>
                    </ul>
                </span>
            </div>

            <div class="tab_content" id="dict_tab_101" style="display:block">
                <div class="part_main">
                    <div class="collins_content">
                        {meanings}
                    </div>
                </div>
            </div>
        </body>
    </div>
    """

    # 函数来生成含义和例句的HTML内容
    def generate_meanings_html(meanings):
        meaning_items_html = ""
        for idx, meaning in enumerate(meanings, 1):
            meaning_item_html = f"""
            <div class="C1_explanation_item">
                <div class="C1_explanation_box">
                    <span class="C1_item_number"><a href="entry://#page_top">{idx}</a></span>
                    <span class="C1_text_blue">{meaning['meaning']}</span>
                </div>
                <ul>
            """

            for example in meaning['examples']:
                meaning_item_html += f"""
                <li>
                    <p class="C1_sentence_en">{example['english']}</p>
                    <p>{example['translation']}</p>
                </li>
                """

            meaning_item_html += "</ul></div>"
            meaning_items_html += meaning_item_html

        return meaning_items_html

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
        html_content = html_template.format(
            word=word_json_data["word"],
            meanings=generate_meanings_html(word_json_data["meanings"])
        )
        return html_content

    except ValueError as ve:
        print(f"错误: {ve}")
        return ""
    except KeyError as ke:
        print(f"错误: {ke}")
        return ""
    except TypeError as te:
        print(f"错误: {te}")
        return ""
    except Exception as e:
        print(f"发生未知错误: {e}")
        return ""
