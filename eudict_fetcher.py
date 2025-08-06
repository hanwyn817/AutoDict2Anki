import requests
from datetime import datetime, timedelta
import os

def is_cookie_valid(cookie: str) -> bool:
    """
    通过请求一个需要验证 cookie 的接口，检查返回结果来判断 cookie 是否有效。
    如果响应内容中包含 "自动登录" ，则认为 cookie 无效。
    请根据实际情况修改 test_url。
    """
    test_url = "https://my.eudic.net"
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
        
        # 保存新cookie到.env文件
        if update_env_cookie(cookie_str):
            print("新cookie已保存到.env文件")
        else:
            print("警告：未能保存新cookie到.env文件，请手动更新")
        
        return cookie_str
    else:
        print("未能在浏览器中获取到任何 cookie。")
        return ""


def update_env_cookie(new_cookie: str) -> bool:
    """
    更新.env文件中的EUDICT_WEB_COOKIE变量
    
    参数:
    - new_cookie (str): 新的cookie字符串
    
    返回:
    - bool: 更新成功返回True，否则返回False
    """
    env_file_path = ".env"
    
    # 检查.env文件是否存在
    if not os.path.exists(env_file_path):
        print(f"错误：{env_file_path} 文件不存在")
        return False
    
    try:
        # 读取.env文件内容
        with open(env_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # 查找并更新EUDICT_WEB_COOKIE行
        cookie_updated = False
        for i, line in enumerate(lines):
            if line.startswith("EUDICT_WEB_COOKIE="):
                lines[i] = f'EUDICT_WEB_COOKIE="{new_cookie}"\n'
                cookie_updated = True
                break
        
        # 如果没有找到EUDICT_WEB_COOKIE行，则添加
        if not cookie_updated:
            lines.append(f'EUDICT_WEB_COOKIE="{new_cookie}"\n')
        
        # 写回文件
        with open(env_file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        
        print("已成功更新.env文件中的cookie")
        return True
    
    except Exception as e:
        print(f"更新.env文件时出错：{e}")
        return False


def get_all_words_data(cookie, start=0, length=200):
    """
    获取欧路词典中所有单词列表。

    参数:
    - start (int): 起始位置，默认值为 0。
    - length (int): 每次请求的单词数量，默认值为 200。

    返回:
    - List[dict]: 包含所有单词信息的字典列表，每个字典包含 id, uuid, exp 和 addtime。
    """
    # 定义请求的参数
    params = {
        "=8": "", 
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
        "categoryid": "-1" # 0: 我的生词本（默认）， -1: 所有生词本
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
        return words_list

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
