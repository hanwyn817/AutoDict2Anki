# AutoDict2Anki

## 项目简介
AutoDict2Anki 是一个自动化单词采集、释义获取并同步到 Anki 牌组的工具。它支持从欧路词典获取生词，通过本地词典或 AI 补全释义，并自动添加到 Anki，帮助用户高效构建个人词库。

## 主要功能
- 自动获取欧路词典生词本中的新单词
- 支持本地 MDX 词典查词，查不到时可调用 AI 补全释义
- 自动将单词和释义添加到指定 Anki 牌组（支持 AnkiConnect）
- 支持定时任务与日志记录
- 支持自定义配置与安全的密钥管理

## 运行前必读：last_run_time.txt 说明

本项目依赖 last_run_time.txt 文件来记录上次运行的时间，用于筛选自上次运行以来新增的单词。

- **首次运行前，必须手动创建并填写 last_run_time.txt 文件。**
- 文件内容为一行时间字符串，格式如下：
  
  ```
  2025-01-01 20:00:00
  ```
- 时间必须为过去的某一时刻，不能晚于当前时间。
- 如果格式不正确或时间晚于当前时间，程序会提示并终止运行。
- 每次运行后，程序会自动更新该文件为本次运行的时间。

## 依赖环境
- Python 3.8 及以上
- 依赖包见 requirements.txt，主要包括：
  - requests
  - schedule
  - selenium
  - webdriver_manager
  - 以及 AnkiConnect 插件（需在 Anki 客户端安装）

## 安装与配置
1. **克隆项目**
   ```bash
   git clone <your_repo_url>
   cd AutoDict2Anki
   ```
2. **创建虚拟环境并安装依赖**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **配置环境变量**
   - 复制 `.env.template` 文件为 `.env`：
     ```bash
     cp .env.template .env
     ```
   - 编辑 `.env` 文件，填入你的密钥和 cookie：
     ```env
     EUDICT_WEB_COOKIE="登录欧路词典网页版https://my.eudic.net/studyList的COOKIE"
     UEDICT_API="欧陆开放API授权信息https://my.eudic.net/OpenAPI/Authorization"
     ANKI_WEB_COOKIE="登录Anki网页版https://ankiuser.net/add的COOKIE"
     AI_API_KEY="Bearer sk-xxx"
     ```
   - 本地词典文件（MDX/MDD）请放在 `resources/` 目录下，路径已在 `config.py` 中配置。

4. **确保 Anki 已安装 AnkiConnect 插件**
   - 打开 Anki，进入插件管理，安装 AnkiConnect（插件号 2055492159）。

## 用法说明
1. **直接运行一次任务**
   ```bash
   python main.py
   ```
2. **定时任务**
   - 可在 `main.py` 中解开 schedule 相关注释，实现每天定时自动同步。

3. **结果查看**
   - 运行结果和日志会输出到 `result.txt` 和控制台。

## 常见问题 FAQ

### 1. 环境变量/密钥未生效？
- 检查 `.env` 文件格式，不能有多余空格或引号错位。

### 2. 欧路/Anki/AI 接口报错？
- 检查对应的 cookie、API 密钥是否正确、未过期。
- 检查网络连接，AnkiConnect 需本地 Anki 客户端开启且插件正常。

### 3. 词典查不到释义？
- 检查 `resources/` 下的 MDX/MDD 文件路径和文件是否完整。
- AI 补全需保证 AI_API_KEY 有效。

### 4. 如何自定义牌组？
- 修改 `config.py` 中的 `ANKI_DECK_NAME`。

### 5. 依赖包安装失败？
- 建议使用虚拟环境，确保 pip 源可用。

### 6. 欧路词典cookie过期怎么办？
- 程序会自动检测cookie有效性，如果失效会提示通过浏览器登录获取新的cookie。

---

如有更多问题或建议，欢迎 issue 或 PR！
