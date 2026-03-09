# AutoDict2Anki

## 项目简介
AutoDict2Anki 是一个自动化单词采集、释义获取并同步到 Anki 牌组的工具。它支持从欧路词典获取生词，通过本地 MDX/MDD 词典或 AI 进行释义提取补充，并自动添加到 Anki，帮助用户高效构建个人词库。最新版本集成了 DeepSeek AI (通过 SiliconFlow) 作为强大的释义 fallback 服务，能够提供具有真实语境且符合特定英语考试要求的例句，并配合 Jinja2 进行 HTML 排版生成精致的单词卡片。

> 如果你计划部署到 Linux VPS / Docker / dpanel，推荐使用 `ANKI_SYNC_METHOD="ankiweb"`，不要使用依赖本地桌面 Anki 的 `ankiconnect` 模式。

## 主要功能
- **自动化同步**: 自动获取欧路词典生词本中的新单词，无需手动导出。
- **双引擎同步 Anki**:
  - **AnkiConnect (本地)**: 将生成的单词和释义自动精准同步到指定的 Anki 本地牌组并且自带重复检查。
  - **AnkiWeb (VPS/无头)**: 内置 Playwright 无头浏览器，直接在 VPS 或服务器环境自动化提交到网页版 AnkiWeb（`https://ankiuser.net/add`），便于 24 小时无人值守。
- **混合释义引擎**: 优先查找本地 MDX 词典（如柯林斯词典），查不到时自动调用 AI API (支持 DeepSeek-V3 等) 补全释义。
- **AI 智能例句生成**: 能够根据配置的考试类型（如：雅思、托福、考研等）生成符合考试场景的中英文例句。
- **精美卡片模板**: 内置 `Jinja2` HTML 模板引擎 (`templates/word_card.html`)，自动将单词、多重释义及例句排版为美观的 Anki 卡片。
- **统一 Cookie 更新工具**: 提供可在纯命令行终端下运行的 `update_cookie.py`，适用于 VPS 服务器无需系统图形界面就能轻松更新各类失效的 Cookie。

## 运行前必读：记录增量更新的游标
本项目依赖 `last_run_time.txt` 文件来记录上次运行的时间和单词 UUID，用于筛选自上次运行以来新增的单词。

- **首次运行前，必须手动创建并填写 `last_run_time.txt` 文件。**
- 文件内容支持写入过去的一个时间字符串（用于兼容旧版本）或 JSON 格式。推荐最初写入单行过去时间，格式如下：
  ```text
  2025-01-01 20:00:00
  ```
- 时间必须为过去的某一时刻，不能晚于当前时间。
- 每次成功拉取单词并同步至 Anki 后，程序会自动更新该文件为 JSON 格式的最新同步游标（包含 `last_addtime` 和 `last_word_uuid`）。
- 容器部署时也可以通过环境变量 `INITIAL_CURSOR_TIME` 在首次启动时自动创建该文件，避免手工进入容器初始化。

## 依赖环境
- 本项目使用 `uv` 管理虚拟环境和依赖包
- Python 3.8 及以上
- 主要依赖包:
  - `requests`
  - `schedule`
  - `playwright` (用于 AnkiWeb 无头操作)
  - `selenium` & `webdriver_manager` (用于本地环境手动登录获取 Eudict Cookie)
  - `jinja2` (用于 HTML 模板渲染)
  - `python-dotenv` (用于加载配置文件)
  - (若使用本地同步) Anki 客户端需安装 **AnkiConnect** 插件（插件代码 `2055492159`）。

## 安装与配置

1. **克隆项目**
   ```bash
   git clone <your_repo_url>
   cd AutoDict2Anki
   ```

2. **安装依赖**
   请确保已安装 [uv](https://docs.astral.sh/uv/)，然后执行同步：
   ```bash
   uv sync
   ```
   *注意：如果您打算使用 AnkiWeb 的同步模式，首次运行时还必须安装 Playwright 的内置浏览器：*
   ```bash
   uv run playwright install chromium
   ```

3. **配置环境变量**
   - 复制 `.env.template` 文件为 `.env`：
     ```bash
     cp .env.template .env
     ```
   - 编辑 `.env` 文件，填入你的配置信息（完整字段可参考 `.env.template`）：
     ```env
     # 欧路词典 Web Cookie
     EUDICT_WEB_COOKIE="你的欧路网页版Cookie"
     UEDICT_API="欧陆开放API授权信息(如有)"
     
     # AI 服务配置 (默认使用 SiliconFlow)
     AI_API_URL="https://api.siliconflow.cn/v1/chat/completions"
     AI_API_KEY="Bearer sk-your-siliconflow-api-key"
     AI_MODEL="Pro/deepseek-ai/DeepSeek-V3"
     USER_TARGET_EXAM="雅思" # 决定 AI 生成例句的场景，如雅思、托福、CET6等
     
     # 本地词典配置
     MDX_FILE_PATH="resources/Collins COBUILD (CN).mdx"
     MDD_FILE_PATH="resources/Collins COBUILD (CN).mdd"
     
     # Anki 同步配置
     ANKI_SYNC_METHOD="ankiconnect" # 可选: ankiconnect (本地) 或 ankiweb (无头网页)
     ANKI_CONNECT_URL="http://127.0.0.1:8765" # 仅在 ankiconnect 模式时生效
     ANKI_WEB_COOKIE="your_anki_web_cookie_here" # 仅在 ankiweb 模式时生效
     ANKI_NOTE_TYPE="基础" # 笔记类型
     ANKI_DECK_NAME="Manki's Daily"

     # 容器部署建议
     DATA_DIR="/app/data"
     CURSOR_FILE_PATH="/app/data/last_run_time.txt"
     FAILED_QUEUE_FILE_PATH="/app/data/failed_words_queue.json"
     RESULT_FILE_PATH="/app/data/result.txt"
     SYNC_INTERVAL_HOURS="12"
     INITIAL_CURSOR_TIME="2025-01-01 00:00:00" # 仅首次部署建议填写
     ```

   - **准备本地词典:** 如果你是直接在本机运行项目，请将 `.mdx` 和 `.mdd` 资源文件放置在项目根目录的 `resources/` 目录下，并确保与 `.env` 中配置的路径一致。  
     如果你是通过 Docker / dpanel 部署，请看后文“Docker / dpanel 部署”章节，那里说的 `resources/` 指的是 **VPS 宿主机上的目录**，再挂载到容器内的 `/app/resources`。

4. **确保 AnkiConnect 插件就绪** *(仅 `ANKI_SYNC_METHOD="ankiconnect"` 模式需要)*
   - 打开您的 Anki 客户端，并在后台保持运行。
   - 在 Anki 中检查附加组件，确保安装并启用了 **AnkiConnect**（安装代码 `2055492159`）。

## 用法说明

### 1. 更新 Cookie
欧路网页版或 AnkiWeb 的 Cookie 可能会到期失效。  

如果你是 **本地运行项目**，或者是通过 `.env` 文件管理配置，推荐使用内置的 CLI 工具更新：
```bash
uv run update_cookie.py
```
程序将提示您选择要更新 `EUDICT_WEB_COOKIE` 还是 `ANKI_WEB_COOKIE`，只需把浏览器网络抓包里找到的最新 Cookie 字符串粘贴进终端回车即可。

*(附：本地机器仍可以使用 `uv run login.py` 自动弹窗扫码获取欧路词典的 Cookie)*

如果你是 **通过 dpanel 页面配置环境变量** 部署容器，请不要依赖 `update_cookie.py`。正确做法是：

- 在你本地电脑的浏览器里获取最新 Cookie
- 回到 dpanel 容器/应用配置页面
- 直接修改 `EUDICT_WEB_COOKIE` 或 `ANKI_WEB_COOKIE`
- 保存配置后重建或重新部署容器，使新的环境变量生效

### 2. 运行单次同步
直接执行主脚本：
```bash
uv run main.py
```
程序将从生词本拉取增量单词，自动查询 MDX 或请求 AI 释义，并根据 `.env` 中 `ANKI_SYNC_METHOD` 的设置推送到 AnkiConnect（本地）或 AnkiWeb（网页端）。运行结果会自动汇总输出到 `result.txt` 以及终端日志中。

### 3. VPS 守护进程模式
若需在服务器端挂机实现自动循环同步，可以通过 `--daemon` 参数启动。启动后会**立即执行一次**同步任务，之后每隔 `SYNC_INTERVAL_HOURS` 小时自动再次执行，默认 `12` 小时。

> **前提：** 请确保 `.env` 中已设置 `ANKI_SYNC_METHOD="ankiweb"` 并配置了有效的 `ANKI_WEB_COOKIE`。

```bash
uv run main.py --daemon
```
*建议配合 `nohup` 或 `tmux` 使用，以保证终端关闭后任务依然在后台执行。*

## Docker / dpanel 部署

项目已经提供了以下容器部署文件：

- `Dockerfile`
- `compose.yaml`
- `docker/entrypoint.sh`

推荐部署方式是让容器长期运行 `uv run python main.py --daemon`，并把运行时状态文件持久化到宿主机。

### 1. 在 VPS 宿主机上准备目录

这里的“准备目录”，指的是在 **Linux VPS 宿主机** 上创建目录，不是在容器里手动创建。

如果你的项目部署目录是 `/opt/AutoDict2Anki`，那么可以这样准备：

```bash
cd /opt/AutoDict2Anki
mkdir -p data resources
```

- `data/` 是 **VPS 宿主机目录**，用于保存运行时状态文件，例如 `last_run_time.txt`、`failed_words_queue.json`、`result.txt`
- `resources/` 也是 **VPS 宿主机目录**，如果你要使用本地词典，就把 `.mdx/.mdd` 文件放到这里

例如，宿主机目录结构应该类似这样：

```text
/opt/AutoDict2Anki/
├── compose.yaml
├── .env
├── data/
└── resources/
    ├── Collins COBUILD (CN).mdx
    └── Collins COBUILD (CN).mdd
```

之后，`compose.yaml` 会把：

- 宿主机 `./data` 挂载到容器 `/app/data`
- 宿主机 `./resources` 挂载到容器 `/app/resources`

所以容器里的：

```env
MDX_FILE_PATH="/app/resources/Collins COBUILD (CN).mdx"
MDD_FILE_PATH="/app/resources/Collins COBUILD (CN).mdd"
```

本质上就是在读取 **宿主机 `resources/` 目录里的词典文件**。

如果你完全依赖 AI 释义，不使用本地词典，那么可以不准备 `resources/`。当前程序在词典文件不存在时，会自动回退到 AI 释义，不会因为缺少 `.mdx/.mdd` 而直接中断容器；前提是 `AI_API_KEY` 已正确配置。

### 2. 配置 `.env`

容器模式最关键的是：

```env
ANKI_SYNC_METHOD="ankiweb"
ANKI_WEB_COOKIE="your_anki_web_cookie_here"
DATA_DIR="/app/data"
CURSOR_FILE_PATH="/app/data/last_run_time.txt"
FAILED_QUEUE_FILE_PATH="/app/data/failed_words_queue.json"
RESULT_FILE_PATH="/app/data/result.txt"
SYNC_INTERVAL_HOURS="12"
INITIAL_CURSOR_TIME="2025-01-01 00:00:00"
MDX_FILE_PATH="/app/resources/Collins COBUILD (CN).mdx"
MDD_FILE_PATH="/app/resources/Collins COBUILD (CN).mdd"
```

说明：

- `INITIAL_CURSOR_TIME` 只在 `last_run_time.txt` 不存在时生效，建议填一个过去时间用于首次启动
- 首次启动成功并生成游标文件后，可以删除 `INITIAL_CURSOR_TIME`
- 若使用本地词典，请先把词典文件放到 **VPS 宿主机的 `resources/` 目录**
- 若暂时还没上传词典文件，只要 `AI_API_KEY` 可用，程序也会自动回退到 AI 释义，不会中断容器

### 3. 本地 Docker Compose 启动

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f autodict2anki
```

### 4. dpanel 部署建议

如果你使用 dpanel 这类容器面板，直接导入仓库里的 `compose.yaml` 即可，然后做这几件事：

- 把 `.env` 中的敏感变量填到面板环境变量或服务器上的 `.env` 文件中
- 将宿主机 `data/` 挂载到容器 `/app/data`
- 如需本地词典，将宿主机 `resources/` 挂载到容器 `/app/resources`
- 首次部署时设置一个过去时间的 `INITIAL_CURSOR_TIME`
- 确保 VPS 能访问 `my.eudic.net`、AI API 服务地址以及 `ankiuser.net`

关于 Cookie 更新：

- 如果你使用的是 dpanel 页面里的环境变量，请在 **本地浏览器获取新 Cookie** 后，直接回到 dpanel 修改环境变量
- 不建议在这种模式下使用 `update_cookie.py`，因为它修改的是容器内 `.env` 文件，不一定能覆盖 dpanel 注入的环境变量，也可能在容器重建后丢失

这个项目不需要对外暴露端口，因为它本质上是后台定时任务，不是 Web 服务。

## 常见问题 FAQ

### 1. "词典查不到释义 / MDX 文件不存在"？
请检查 `resources/` 下是否存在您在 `.env` 中指定的同名 `.mdx`/`.mdd` 文件。如果没有本地词典，程序将自动走到 AI 释义分支。

### 2. "AI 释义失败 / 接口报错"？
确认 `AI_API_KEY` 是有效的（注意开头是否带有 `Bearer `）。默认采用的是 SiliconFlow 平台，你可以根据需要将 `AI_API_URL` 更换成兼容 OpenAI 格式的其他提供商。

### 3. Anki 返回 "AnkiConnect canAddNotes 失败"？ *(ankiconnect 模式)*
- 确认您的 Anki 已经处于运行状态。
- 确认配置的 `ANKI_DECK_NAME` 在 Anki 中真实存在。
- `ANKI_CONNECT_URL` 是否是 `http://127.0.0.1:8765`，且没有被其他程序占用。

### 4. AnkiWeb 添加失败？ *(ankiweb 模式)*
- **"AnkiWeb 登录失效"**：Cookie 已过期。  
  如果你是本地 `.env` 部署，请运行 `uv run update_cookie.py` 更新 `ANKI_WEB_COOKIE`。  
  如果你是 dpanel 环境变量部署，请在本地浏览器获取新 Cookie 后，回到 dpanel 修改 `ANKI_WEB_COOKIE` 并重新部署容器。
- **"未能找到牌组"**：确认 `.env` 中的 `ANKI_DECK_NAME` 与 AnkiWeb 上的牌组名称完全一致（区分大小写和空格）。
- **"页面加载超时"**：可能是网络问题或 AnkiWeb 页面结构已更新，请检查 VPS 的网络连通性。

### 5. 程序报错“Cookie 无效”？
欧路或 AnkiWeb 的 Cookie 在一段时间后会自动过期。

- 如果你是本地 `.env` 部署，最快的解决办法是运行 `uv run update_cookie.py`
- 如果你是 dpanel 环境变量部署，请在本地浏览器获取新的 Cookie 后，回到 dpanel 修改对应环境变量，并重新部署容器

本地环境也可以使用 `uv run login.py` 打开浏览器重新登录获取欧路 Cookie。

### 6. 容器里首次启动就提示缺少 `last_run_time.txt`？

- 检查是否已经挂载了 `/app/data`
- 检查 `INITIAL_CURSOR_TIME` 是否设置为一个过去时间，例如 `2025-01-01 00:00:00`
- 如果游标文件已经生成，后续不要反复修改它，程序会自行推进

## 致谢
本项目的本地 MDX/MDD 词典解析功能使用了 [mdict-analysis](https://github.com/hehonghui/mdict-analysis) 库。

---

如有更多问题或建议，欢迎 issue 或 PR！
