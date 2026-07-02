---
name: hermes-skill-onboarding
description: 把一套外部文件/数据（压缩包、脚本、凭证）落地成某个用户 hermes 容器里的可执行 skill 并验证。当用户说“把这些文件部署到 XX 的 hermes”“给新用户/新容器创建 skill”“把这个任务接到平台跑”“落地这套数据到容器”时使用。流程：分析文件→定位目标容器→核实凭证（缺了就问）→部署 skill+工作目录→准备运行时→验证→飞书文本渠道测试→可选 cron。覆盖 pyc 版本匹配、凭证持久化、lark-cli vs lark-oapi、cron ticker 误报等实测坑。
allowed-tools: Bash(docker exec:*), Bash(docker cp:*), Bash(docker ps:*), Bash(docker images:*), Bash(psql:*), Read, Write, Edit
---

# 把外部任务落地成 hermes 用户 skill

把用户给的一套文件（脚本、数据、可能的凭证）变成某个用户 hermes 容器里能跑的 skill，并验证。

## 核心原则
- **缺信息就问，不要猜**（凭证、目标用户、推送目标）
- 一个任务可能要拆成多个 skill（见“拆分原则”）
- 飞书测试优先**文本渠道**（用户登录扫码绑定后 hermes 渠道即可用）

## 前置信息清单（缺哪项问哪项）
| 信息 | 说明 | 缺了怎么办 |
|---|---|---|
| 目标用户 | 哪个账号的 hermes | 查 users 表 + 运行中 `hermes-user-*` 容器，让用户确认 |
| 文件数据 | 压缩包路径 | 问用户要 |
| 凭证 | Odoo/飞书/其他 | 包里通常**故意不含**（README 会声明），从原运行环境导出 |
| 推送目标 | chat_id / 邮箱 | 查 `channel_directory.json`；或问用户 |

## 流程

### 1. 分析文件
解压（Windows 打的包用反斜杠路径，用 python `zipfile` 统一）。识别：
- 脚本/可执行（`.py` / `.pyc` / `.sh`）
- 数据文件（`.xlsx` / `.json` / `.csv`）
- 凭证边界：`grep` 明文密码/key/secret；README 通常写“不含敏感信息”
- 运行时要求：pyc 的 magic number 决定 python 版本；`import` 的依赖

### 2. 定位目标容器
```bash
docker exec openclaw-postgres psql -U nanobot -d nanobot_platform \
  -c "SELECT left(id::text,8), username, role FROM users ORDER BY created_at;"
docker ps --filter name=hermes-user
```
选**有运行中容器**的用户。`HERMES_HOME=/opt/data`，workdir=`/opt/data`。

### 3. 核实凭证与缺口
列清单，缺的用 AskUserQuestion 或直接问。**凭证通常不在包里（设计如此），要从原运行环境导出**。给原机器一段导出命令（PowerShell/env/lark-cli 配置）。

### 4. 设计 skill 结构
- skill：`/opt/data/skills/<name>/`（`SKILL.md` + `scripts/` + `references/`）
- 工作数据：`/opt/data/<name>/`（数据卷，容器重建不丢）
- 凭证：`/opt/data/<name>/.env`（600 权限）—— **不要写 `/opt/data/.env`**，那是 hermes 的，容器重建会被擦
- 运行时：`/opt/data/<name>/venv`（需特定 python 版本时）

### 5. 部署
```bash
docker cp <src>/. <C>:/opt/data/skills/<name>/
docker cp <data>/. <C>:/opt/data/<name>/
docker exec <C> chmod +x <scripts>
docker exec <C> chown -R hermes:hermes /opt/data/skills/<name> /opt/data/<name>
```

### 6. 运行时准备
pyc 的 magic number 锁定 python 版本（如 `cpython-312` → 必须 3.12）。容器自带可能是 3.13，跑不了 3.12 pyc。用 uv 建 venv：
```bash
docker exec -u hermes <C> uv venv --python 3.12 /opt/data/<name>/venv
docker exec -u hermes <C> uv pip install --python /opt/data/<name>/venv/bin/python <deps>
```
runner 用 `sys.executable` 调 pyc，所以**用 venv 的 python 跑 runner**，pyc 自动落在对的版本。

### 7. 验证
- **offline**（用包内夹具/原始 JSON 回放）：`<venv>/bin/python <runner> --offline`，对比产出与基线
- **online**（注入凭证跑）：对比指标合理性（结构指标应稳定，数值类可能因时效性小幅变化，正常）

### 8. 飞书渠道：P2P 就是 hermes 对话（最后一步）
用户登录平台 → 扫码绑定飞书（device flow）→ bot 联通 → 产生 P2P chat，**这就是用户和 hermes 的私聊会话本身**。

**P2P 场景不需要任何外部发送脚本**——推送走 hermes 原生渠道：
- **定时推送（首选）**：cron job 配 `--deliver feishu:<P2P chat_id>`，脚本 stdout（日报文本）由 cron 自动走渠道投递，零外部脚本、零 lark-cli。
- **对话内**：agent 在 P2P 会话里用 `send_message` 工具发，就是"飞书和 hermes 对话"。

**只有两种情况才需要外部脚本（直接 HTTP）**：发**交互卡片**（send_message 只发文本，卡片必须直接 HTTP，见坑 4）；或一次性连通性测试。

查可达目标：
```bash
docker exec <C> cat /opt/data/channel_directory.json   # 找 feishu 下 type=dm 的 chat_id
```
直接 HTTP（仅卡片/测试用，`.env` 凭据换 token）：
```python
# 读 /opt/data/.env 拿 app_id/app_secret
# POST /open-apis/auth/v3/tenant_access_token/internal  → token
# POST /open-apis/im/v1/messages?receive_id_type=chat_id
#   {receive_id, msg_type:"text", content:json({"text":...})}
```
bot 在 P2P chat 里天然能发，**不需要拉群**。

### 9.（可选）配 cron 定时
```bash
docker exec -u hermes <C> /opt/hermes/.venv/bin/hermes cron create "0 10 * * 1-5" \
  --name <name> --no-agent --script <script.sh> --workdir /opt/data/<name>
```
cron script 要放 `/opt/data/scripts/`（path-traversal 校验）。验证自动触发：`hermes cron run <id>` 后等一个 tick（60s）看 `cron/output/`。

## 多 skill 拆分原则
一套任务文件是否拆成多个 skill：
- 数据获取 / 业务分析 / 推送，若各自能被**别的任务独立复用** → 拆
- 强耦合、共享数据/凭证/产物 → 合一个
- 拆的话，每个 skill 独立 `SKILL.md`，共享数据放同一个工作目录

## 关键坑（实测，详见 references/pitfalls.md）
- pyc 锁 python 版本（magic number，跨版本 `bad magic number`）
- 凭证存工作目录 `.env`，**不碰** hermes `/opt/data/.env`（重建擦除，记忆第 1 节）
- hermes 内置 `lark-oapi`（Python SDK）≠ `lark-cli`（CLI 二进制），发送层要分清
- `send_message` 工具 / cron deliver **只发文本**，交互卡片要直接 HTTP/lark-oapi
- `hermes cron status` 报 "Gateway not running" 常是**误报**（ticker 在 PID 1 gateway 跑，`run.py:16988`），看进程别看 CLI

## 案例
完整落地过程见 `references/case-sales-daily-report.md`。
