import requests
from datetime import datetime, timedelta

def is_cookie_valid(cookie: str) -> bool:
    """
    通过请求一个需要验证 cookie 的接口，检查返回结果来判断 cookie 是否有效。
    如果响应内容中包含 "自动登录" ，则认为 cookie 无效。
    请根据实际情况修改 test_url。
    """
    test_url = "https://my.eudic.net"  # 请替换为实际的测试接口地址
    headers = {"Cookie": cookie}
    try:
        response = requests.get(test_url, headers=headers, timeout=10)
        # 判断响应内容中是否包含“自动登录”
        if "自动登录" in response.text:
            print("检测到响应中包含'自动登录'，认为 cookie 已失效。")
            return False
        # 如果状态码为200且不包含“自动登录”，则认为 cookie 有效
        if response.status_code == 200:
            return True
    except Exception as e:
        print("测试 cookie 时出错：", e)
    return False

def get_cookie_via_browser() -> str:
    """
    通过 Selenium 弹出浏览器，供你手动登录后获取新的 cookie。
    此示例使用 Chrome 浏览器，同时用 webdriver_manager 自动管理驱动。
    请确保安装了 selenium 和 webdriver_manager：
        pip install selenium webdriver_manager
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager

    # 初始化 Chrome 浏览器
    options = webdriver.ChromeOptions()
    # 可根据需要添加其他选项，例如无头模式：options.add_argument('--headless')
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

    login_url = "https://dict.eudic.net/Account/Login"  # 请替换为实际的登录页面 URL
    driver.get(login_url)
    print("浏览器已打开，请在浏览器中手动完成登录。")
    print("登录完成后，请在此命令行中按回车继续...")
    input()  # 等待用户确认登录完成

    # 示获取浏览器中的所有 cookie，返回一个字典列表
    cookies = driver.get_cookies()
    driver.quit()

    if cookies:
        # 拼接成标准的 Cookie 字符串，如 "name1=value1; name2=value2; ..."
        cookie_str = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
        print("获取到新的全部 cookie：", cookie_str)
        return cookie_str
    else:
        print("未能在浏览器中获取到任何 cookie。")
        return ""


def get_new_words(cookie, days=1, start=0, length=200):
    """
    获取欧路词典中新增的单词列表。

    参数:
    - start (int): 起始位置，默认值为 0。
    - length (int): 每次请求的单词数量，默认值为 100。

    返回:
    - List[dict]: 包含新增单词信息的字典列表，每个字典包含 id, uuid, exp 和 addtime。
    """
    # 定义请求的参数
    params = {
        "=8": "",  # 或者填入适当的值
        "draw": 2,
        "columns[0][data]": "id",
        "columns[1][data]": "id",
        "columns[2][data]": "word",
        "columns[3][data]": "phon",
        "columns[4][data]": "exp",
        "columns[5][data]": "rating",
        "columns[6][data]": "addtime",
        "start": start,
        "length": length,
        "categoryid": "studyList",
    }

    url = "https://my.eudic.net/StudyList/WordsDataSource"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": cookie
    }

    try:
        # 发送 GET 请求
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status() # 检查请求是否成功

        # 解析 JSON 响应
        data = response.json()
        words = data.get('data', [])
        if not words:
            print("No new words found.")
            return []

        # 提取单词信息
        words_list = [
            {'id': word.get('id'), 'uuid': word.get('uuid'), 'exp': word.get('exp', ''),
             'addtime': word.get('addtime', '')}
            for word in words
        ]

        # 获取指定天数内新增的单词
        current_time = datetime.now()
        time_24_hours_ago = current_time - timedelta(days=days) # 设置天数范围
        recent_data = [entry for entry in words_list if datetime.fromisoformat(entry['addtime']) > time_24_hours_ago]
        return recent_data

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return []
    except ValueError as e:
        print(f"Error parsing response JSON: {e}")
        return []

# if __name__ == "__main__":
#     cookie = config.EUDICT_WEB_COOKIE
#     if not is_cookie_valid(cookie):
#         print("当前 cookie 无效，尝试通过浏览器手动登录获取新的 cookie...")
#         new_cookie = get_cookie_via_browser()
#         if new_cookie:
#             cookie = new_cookie
#         else:
#             print("获取新的 cookie 失败，程序终止。")
#     else:
#         get_new_words(cookie)
