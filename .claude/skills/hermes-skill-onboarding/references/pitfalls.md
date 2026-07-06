# 实测坑与解法

落地外部任务到 hermes 容器时高频踩到的坑，每条附代码位置和解法。

## 1. pyc 锁定 Python 版本
- **现象**：`bad magic number` 或 `ValueError: bad marshal data (unknown type code)`。
- **根因**：pyc 的 magic number 标明编译时的 Python 版本（如 `cb0d0d0a` = 3.12.0）。容器自带的 Python（如 3.13）marshal 格式不兼容，跨版本读不了 code object。
- **解法**：用 uv 建对应版本 venv：`uv venv --python 3.12 /opt/data/<name>/venv`。runner 用 `sys.executable` 调 pyc，所以用 venv 的 python 跑 runner 即可。
- **注意**：pyc 的 magic 查 CPython 源码 `Lib/importlib/_bootstrap_external.py` 的 `MAGIC_NUMBER`，或直接 `python -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())"` 对照。

## 2. 凭证位置：工作目录 .env，不是 hermes 的 .env
- **坑**：把凭证写进 `/opt/data/.env`（hermes 的），容器重建（rebuild）时 platform 的 `_build_hermes_env_file` 会重写它，只保留 `FEISHU_*` 等前缀（`manager.py` preserve_vars），Odoo/业务凭证丢失。
- **解法**：凭证写进**工作目录** `/opt/data/<name>/.env`（数据卷，重建不丢），脚本开头 `source` 它：
  ```bash
  [ -f /opt/data/<name>/.env ] && set -a && . /opt/data/<name>/.env && set +a
  ```
  `chmod 600` 保护，属主 hermes。详见项目记忆第 1/33 节。

## 3. lark-oapi（SDK）≠ lark-cli（CLI）
- **现象**：脚本调 `shutil.which("lark-cli")`，容器里找不到。
- **根因**：hermes 容器内置的是 `lark-oapi`（Python 包，在 `/opt/hermes/.venv`，给 agent 收发用），不是 `lark-cli`（命令行二进制）。两者不是一回事。
- **解法**：发送层改直接 HTTP（用 `.env` 的 `FEISHU_APP_ID/SECRET` 换 `tenant_access_token`，POST `/open-apis/im/v1/messages`），不依赖 lark-cli。或用 lark-oapi SDK。**别去容器里装 lark-cli**（引入 node 依赖，没必要）。

## 4. send_message / cron deliver 只发文本
- **现象**：想发交互卡片，但 `send_message` 工具只收 `message`（字符串），无 card/msg_type 参数。
- **根因**：`tools/send_message_tool.py` 的 `_handle_send` 只处理文本+媒体；`gateway/platforms/feishu.py:870` 的 `interactive/card` 处理是**接收**方向。
- **解法**：卡片直接 HTTP 发（`msg_type=interactive`，content=json(card)）。日报这种富展示可复用原脚本的卡片构建函数（如 `build_daily_cards`），只把发送层换成 HTTP。

## 5. hermes cron status 的 "Gateway not running" 常是误报
- **现象**：`hermes cron status` 或 `cron list` 报 "Gateway is not running — jobs won't fire"。
- **根因**：CLI 检测 gateway 的方式（health socket/PID）和 platform 的 nanobot overlay 入口（`nanobot_hermes.py` → `hermes_cli.main`）不匹配。实际 gateway 进程在 PID 1 跑（`gateway_state.json` 的 `gateway_state: running`），且 `run.py:16988` 启动了 `cron-ticker` 线程。
- **判断真实状态**：`docker exec <C> ps -ef | grep gateway`（看 PID 1 是否 `gateway run`）+ `gateway_state.json`。别信 CLI status。
- **实测 ticker**：`hermes cron run <id>` + 等 60s，看 `cron/output/<id>/` 有没有执行记录。

## 6. Windows 打的 zip 用反斜杠路径
- **现象**：`unzip` 警告 "appears to use backslashes as path separators"，解压出一堆带 `\` 的怪文件名。
- **解法**：用 python `zipfile` 解压，`name.replace('\\', '/')` 统一。

## 7. 凭证/数据通常故意不在包里
- **现象**：压缩包 README 写 "No passwords, app secrets, or API keys included"。
- **根因**：设计如此，原机器靠环境变量 + 本机工具配置注入。
- **解法**：别当成"漏发"。给原机器一段导出命令（PowerShell 查环境变量 / lark-cli 配置 / Codex env），让用户搬过来。mapping 这类业务数据文件也常常要单独要。

## 8. hermes 不在 PATH（运行态）
- **现象**：`hermes` 命令找不到。
- **解法**：用绝对路径 `/opt/hermes/.venv/bin/hermes`。记忆第 12 节。

## 9. P2P 推送别上外部脚本——它就是 hermes 对话
- **认知**：P2P chat（`channel_directory.json` 里 feishu 的 `type=dm`）是用户和 hermes 的**私聊会话本身**，不是"外部目标"。hermes 在这个对话里直接发即可。
- **正确做法**：定时推送用 cron `--deliver feishu:<P2P chat_id>`（脚本 stdout 走渠道投递）；对话内用 `send_message` 工具。零外部脚本、零 lark-cli。
- **反模式**：写个 Python 脚本直接调飞书 API（换 token + POST /im/v1/messages）发 P2P——多此一举，绕开了 hermes 渠道，还要自己管 token/重试。
- **例外（才用直接 HTTP）**：发**交互卡片**（`send_message` 只支持文本）；或一次性连通性测试。
