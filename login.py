import os

def update_env_cookie(new_cookie: str) -> bool:
    """
    更新 .env 文件中的 EUDICT_WEB_COOKIE 变量。
    """
    env_file_path = ".env"
    if not os.path.exists(env_file_path):
        print(f"错误：{env_file_path} 文件不存在")
        return False

    try:
        with open(env_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        cookie_updated = False
        for i, line in enumerate(lines):
            if line.startswith("EUDICT_WEB_COOKIE="):
                lines[i] = f'EUDICT_WEB_COOKIE="{new_cookie}"\n'
                cookie_updated = True
                break

        if not cookie_updated:
            lines.append(f'EUDICT_WEB_COOKIE="{new_cookie}"\n')

        with open(env_file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as exc:
        print(f"更新 .env 文件时出错：{exc}")
        return False


def get_cookie_via_browser() -> str:
    """
    通过 Selenium 弹出浏览器，供用户手动登录后获取新的 cookie。
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

    login_url = "https://dict.eudic.net/Account/Login"
    driver.get(login_url)
    print("浏览器已打开，请在浏览器中手动完成登录。")
    print("登录完成后，请在此命令行中按回车继续...")
    input()

    cookies = driver.get_cookies()
    driver.quit()

    if not cookies:
        print("未能在浏览器中获取到任何 cookie。")
        return ""

    cookie_str = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
    print(f"已获取新的 cookie（长度: {len(cookie_str)}）")

    if update_env_cookie(cookie_str):
        print("新 cookie 已保存到 .env 文件")
    else:
        print("警告：未能保存新 cookie 到 .env 文件，请手动更新")
    return cookie_str


if __name__ == "__main__":
    print("开始获取欧路词典 Cookie...")
    get_cookie_via_browser()
