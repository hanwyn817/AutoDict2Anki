import os
import sys


def update_env_cookie(key: str, new_cookie: str) -> bool:
    """
    更新 .env 文件中指定的配置变量。
    """
    env_file_path = ".env"
    try:
        if not os.path.exists(env_file_path):
            lines = []
        else:
            with open(env_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        cookie_updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f'{key}="{new_cookie}"\n'
                cookie_updated = True
                break

        if not cookie_updated:
            lines.append(f'{key}="{new_cookie}"\n')

        with open(env_file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as exc:
        print(f"更新 .env 文件时出错：{exc}")
        return False


def main():
    print("=== AutoDict2Anki Cookie 更新工具 ===")
    
    # Check if a target variable was provided as an argument
    target = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["eudict", "eudict_web_cookie"]:
            target = "EUDICT_WEB_COOKIE"
        elif arg in ["anki", "ankiweb", "ankiweb_cookie"]:
            target = "ANKI_WEB_COOKIE"
        else:
            print(f"未知的参数: {arg}")
            print("可用参数: eudict, anki")
            
    # Interactive menu if no valid argument was provided
    if not target:
        print("请选择要更新的 Cookie:")
        print("1. 欧路词典 Web Cookie (EUDICT_WEB_COOKIE)")
        print("2. AnkiWeb Cookie (ANKI_WEB_COOKIE)")
        print("0. 退出")
        while True:
            choice = input("请输入选项编号: ").strip()
            if choice == "1":
                target = "EUDICT_WEB_COOKIE"
                break
            elif choice == "2":
                target = "ANKI_WEB_COOKIE"
                break
            elif choice == "0":
                print("退出...")
                return
            else:
                print("无效的选项，请重新输入。")

    print(f"\n您选择了更新 [{target}]")
    print("-" * 50)
    print("请粘贴新的 Cookie 字符串（然后按回车确认）：")
    new_cookie = input().strip()

    if not new_cookie:
        print("错误：Cookie 不能为空。更新已取消。")
        return

    if update_env_cookie(target, new_cookie):
        print("-" * 50)
        print(f"成功: {target} 已成功更新并保存到 .env 文件中！")
    else:
        print("-" * 50)
        print(f"错误: 无法保存 {target}，请检查 .env 的权限。")


if __name__ == "__main__":
    main()
