---
name: multiuserclaw-archive
description: 从 memory.md 精简归档的详细过程/架构图/方案评估/验证步骤原文（备查）
metadata:
  type: project
---

# MultiUserClaw 记忆详细归档

主文件 `memory.md` 精简后，以下原文（过程、架构图、方案评估、手动流程、验证步骤）归档于此。每个归档段标注对应主文件的原节号，便于回溯。内容未经删改。

---

## 归档 A — 对应原第 11 节：前端终端架构原理

**问题**：在前端 UI 的实时终端中输入 `hermes` 提示找不到命令。

**原理**：

```
前端 terminal UI (xterm.js)
    │ WebSocket ws://host:9900/api/terminal/ws?token=xxx
    ↓
platform gateway (proxy.py:886 proxy_terminal_websocket)
    │ docker exec hermes-user-xxx sh -lc "bash -il"
    │ tty=True, socket=True (Docker PtySocket 模式)
    ↓
hermes-user 容器内的 bash 进程
    │ stdin/stdout 通过 WebSocket 双向流转发
    ↓
前端实时渲染终端输出
```

**代码位置**：
- `proxy.py:886` — `@router.websocket("/terminal/ws")`
- `proxy.py:922` — hermes 后端走 `_bridge_hermes_terminal_websocket`
- `proxy.py:1018-1025` — `_start_hermes_terminal_socket`：`docker exec ["sh", "-lc", command]`

**hermes 找不到的原因**：
- hermes 装在 `/opt/hermes/.venv/bin/hermes`
- 容器 PATH = `/opt/data/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`
- **缺少 `/opt/hermes/.venv/bin`**

**终端默认工作目录**：`workdir="/workspace"`，对应容器的 `/workspace`（指向 hermes-data-xxx 卷）

**正确的使用方式**：
```bash
/opt/hermes/.venv/bin/hermes sessions list
/opt/hermes/.venv/bin/hermes profile list
```
或在 `~/.bashrc` 中添加 `export PATH="/opt/hermes/.venv/bin:$PATH"`

**优化建议**：Dockerfile `ENV PATH` 中加入 `/opt/hermes/.venv/bin`，一行修复。

**代码位置**：`hermes-agent/Dockerfile:136` — `ENV PATH="/opt/data/.local/bin:${PATH}"`

---

## 归档 B — 对应原第 13.1 节：飞书渠道手动配置 workaround（已验证可用）

**绕过 UI 直接操作 hermes-user 容器的完整流程**：

1. 找容器：`docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' | rg 'hermes-user'`，目标 `hermes-user-{user_id前8位}`

2. 写飞书配置到 `/opt/data/.env`：
```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_DOMAIN=feishu
FEISHU_CONNECTION_MODE=websocket          # 长连接，无需公网入站
FEISHU_ALLOW_ALL_USERS=true
FEISHU_GROUP_POLICY=open
FEISHU_REQUIRE_MENTION=true
```

3. 装依赖（lark-oapi 是 `[feishu]` extra，未预装）：
```bash
docker exec -u root hermes-user-xxx bash -lc \
  'uv pip install --python /opt/hermes/.venv/bin/python "lark-oapi==1.5.3" "qrcode==7.4.2"'
```

4. 重启容器：`docker restart hermes-user-xxx`

5. 验证连接：`docker logs --tail 200 hermes-user-xxx | rg -i 'feishu|lark|connected'`，看到 `✓ feishu connected`

6. 给机器人发消息后，从 sessions.json 拿到飞书会话信息：
   - `chat_id`（如 `oc_xxx`）
   - `sender` open_id（如 `ou_xxx`）
   - session key 格式：`agent:main:feishu:dm:{chat_id}`

7. 可用飞书官方 API（带 app_access_token）主动发消息验证发送链路

**关键问题（持久化）**：这个配置**没有通过平台 UI 持久化**。平台重建/启动用户容器时 `manager.py:_write_hermes_runtime_files` 会重写 `/opt/data/.env`，`FEISHU_*` 配置被覆盖。要稳定使用，必须把这些配置写进平台生成 Hermes .env 的逻辑（`_build_hermes_env_file`），而不是手动进容器改。

**已验证的环境**：`hermes-user-2cc7aeaf`，chat_id=`oc_32e53cca8eda504e4e676a21b29b66a9`，sender=`ou_55f3f8250427c83e380f0a25056b5d1c`

---

## 归档 C — 对应原第 15 节：hermes 官方 profile 目录结构

来源：`hermes-agent/docker/entrypoint.sh:40-90` 的 `sync_nanobot_packaged_agents()` 函数

```
${HERMES_HOME}/profiles/{agent_name}/
├── SOUL.md                    ← 人格定义（从 deploy_copy/Agents/{name}/SOUL.md 复制）
├── workspace/
│   ├── AGENTS.md              ← 系统提示词
│   ├── IDENTITY.md            ← 身份定义
│   └── knowledge/             ← 知识库
├── memories/
│   └── USER.md                ← 用户记忆（从 deploy_copy 复制）
├── skills/                    ← 专属技能
├── sessions/                  ← （模板预建，但实际会话存全局 /opt/data/sessions/）
├── skins/                     ← 皮肤配置
├── logs/                      ← 日志
├── plans/                     ← 执行计划
├── cron/                      ← 定时任务
└── home/                      ← agent 家目录
```

**注册 agent（无 profile 时的 fallback）**：使用根路径公共配置
```
/opt/data/SOUL.md              ← agent:main 的人格（无 profile 时）
/opt/data/workspace/           ← 公共工作空间
/opt/data/skills/              ← 公共技能
/opt/data/memories/            ← 公共记忆
```

**预置 agent 模板**（deploy_copy/Agents/）：`main`、`manager`、`programmer`、`researcher`、`hr`、`doctor`

---

## 归档 D — 对应原第 18 节：模型配置 管理员 vs 用户 UI 架构图

### 架构

```
                      model_provider_configs (DB 表，唯一数据源)
                               │
              ┌────────────────┴────────────────┐
              │                                  │
         读 (GET)                            读+写 (PUT)
              │                                  │
    ┌─────────┴──────────┐            ┌──────────┴──────────┐
    │                     │            │                     │
用户端 (3080)        管理端 (3081)   用户端 (3080)       管理端 (3081)
GET /api/openclaw    GET /api/admin   PUT /api/openclaw   PUT /api/admin
/models              /models          /models/config      /models
    │                     │            │                     │
proxy.py 读同一张表    admin.py      proxy.py:418         admin.py:405
    │                     │          {"ok": false} ❌      直写DB ✅
    ↓                     ↓
用户看到列表 ✅        管理员配置 ✅       前端不检查 ok 字段，
                                        看起来成功实际无效
```

### 用户端的三个问题

1. **聊天页没有模型选择器**：`Chat.tsx` 全文 1268 行，没有 `model` 字段，模型绑定在 agent/session 级别，用户不能选
2. **AI模型页所有写操作无效**：`PUT /api/openclaw/models/config` 被 `proxy.py:418` 拒绝返回 `{"ok": false}`，但前端 `fetchJSON` 只要 HTTP 200 就当成功，用户看到"已保存"实际什么都没变
3. **用户能改默认模型吗？** ❌ 调同一个拒绝 API，假成功

### 管理端才是唯一真入口

管理端（`manage_front/.../models/page.tsx`）页面提示：
> "只有这里启用并配置 Key 的模型会出现在用户端"

**代码位置**：
- 用户端：`frontend/src/pages/AIModels.tsx` + `proxy.py:418-419`
- 管理端：`manage_front/src/app/(admin)/models/page.tsx` + `admin.py:399-447`
- 两者读同一张表：`model_config.py:180` `get_model_config_payload`

---

## 归档 E — 对应原第 22 节：飞书通道前端接入方案评估（已被第 26 节最小方案取代）

### 目标
前端点击「接入飞书机器人」→ 选择有/无机器人 → 有则输入凭证，无则扫码接入。

### 关键发现：hermes 已内置 `gateway setup` 向导
**`hermes gateway setup`**（`hermes_cli/main.py:1709 cmd_setup`）是官方交互式向导，自带两种模式：
- **Scan-to-Create（扫码创建）**：选 Feishu/Lark → 终端显示二维码 → 飞书 App 扫码 → **自动创建带正确权限的机器人应用并保存凭证**
- **Manual（手动）**：扫码不可用回退，输入 app_id/app_secret

配置写入 `~/.hermes/.env`（即 `/opt/data/.env`），默认 `FEISHU_CONNECTION_MODE=websocket`（无需公网入站）。

### 三大阻断点（当前前端无法接入的原因）
1. **`hermes-agent/Dockerfile.bridge`** 未预装 `[feishu]` extra（lark-oapi + qrcode），setup 扫码跑不起来
2. **`platform/app/container/manager.py:248` `_build_hermes_env_file()`** 每次完全重写 `/opt/data/.env`，只写 6 行 platform 变量，**不读 existing** → FEISHU_* 被覆盖
3. **`platform/app/routes/proxy.py:352-375`** 渠道 API 全返回空 stub，前端 `Channels.tsx`（1235 行）有界面但无效

### 实现方案（复用 hermes setup，不重复造轮子）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 1. 预装依赖 | `hermes-agent/Dockerfile.bridge` | `uv pip install -e ".[feishu]"`（pyproject.toml:150 已定义 feishu extra） |
| 2. 持久化 FEISHU_* | `manager.py:248,421` | `_build_hermes_env_file` 读 existing 的 FEISHU_*/TELEGRAM_* merge 进新 .env |
| 3. 后端路由 | `routes/channels.py`（新） | `GET /feishu/status`（读 .env + 日志）+ `POST /feishu/restart`（docker restart 用户容器） |
| 4. 前端 | `frontend/src/pages/Channels.tsx` | 「接入飞书」按钮 → terminal modal 跑 `hermes gateway setup`（复用 Terminal.tsx:28 的 WebSocket） |

### 改动量
- 后端 ~60 行 + 前端 ~150 行 + Dockerfile 1 行 = **中等，1-2 天**
- MVP（前端按钮跳现有 Terminal 页手动跑命令）：**半天**

### 完整方案文档
`/home/fjd/.claude/plans/whimsical-wishing-quilt.md`

---

## 归档 F — 对应原第 26 节：飞书快捷接入扫码方案落地细节

### 关键事实（源码已确认）
hermes **真的内置飞书扫码创建机器人**，无需自己写扫码逻辑：
- `hermes_cli/gateway.py:4332` `_setup_feishu()` 两种方式：
  - `"Scan QR code to create a new bot automatically (recommended)"` — 扫码自动创建
  - `"Enter existing App ID and App Secret manually"` — 手动输入
- 选扫码 → `from gateway.platforms.feishu import qr_register`（gateway.py:4359）→ `qr_register()` 用 lark-oapi 调飞书开放平台，扫码授权后自动创建带权限的机器人，返回 app_id/app_secret
- 命令链：`hermes gateway setup` → 选 Feishu → 选 Scan QR code

### 方案决策（重要）
第 22 节评估的完整方案含 3 块改动（Dockerfile 装依赖 + manager.py 保留 FEISHU_* + 前端内嵌终端）。**用户改为最小冲突方案**：不改后端，纯前端弹窗引导复制命令。

- ❌ manager.py 保留 FEISHU_* 改动：**已回滚**（git restore，文件干净）
- ❌ Dockerfile.bridge 装飞书依赖：**未改**
- ✅ 只改 `frontend/src/pages/Channels.tsx`

### 落地改动（仅 Channels.tsx，~70 行）
1. 加 2 个 state：`feishuGuideOpen`、`feishuCopied`
2. 「可用渠道」标题旁加「🪽 扫码接入飞书」按钮
3. 弹窗：步骤引导 + 命令 `/opt/hermes/.venv/bin/hermes gateway setup`（一键复制）+ 依赖失败备用命令 +「打开实时终端」按钮 `navigate('/terminal')`

### 当前限制（用户已知并接受）
1. **飞书依赖未预装**：扫码可能因缺 lark-oapi/qrcode 失败。弹窗提示手动装：`uv pip install --python /opt/hermes/.venv/bin/python "lark-oapi==1.5.3" "qrcode==7.4.2"`
2. **容器重建丢配置**：manager.py 没改，平台重建用户容器时 `_build_hermes_env_file`（manager.py:248）仍覆盖 /opt/data/.env，FEISHU_* 丢失需重新 setup。

---

## 归档 G — 对应原第 27 节：前端终端 xterm.js 升级细节

**背景**：用户在前端终端跑 `hermes gateway setup`（飞书扫码向导）乱码、不能交互。放弃 device flow 网页化（~235 行），改升级前端终端本身——更省且复用面广（所有 hermes 交互命令都受益）。

**根因**：原 `Terminal.tsx` 是 `<div>{termOutput}</div>` 纯文本拼接，不是终端模拟器 → ANSI 颜色码/光标控制/清屏/二维码全乱码，curses 向导无法交互。**后端 PTY 是好的**（`proxy.py:1027` `tty=True` 真 PTY）。

**改动**：`frontend/src/pages/Terminal.tsx` 整体重写为 xterm.js
- 依赖：`@xterm/xterm@^6.0.0` + `@xterm/addon-fit@^0.11.0`（`package.json` + `package-lock.json` 已更新，本地 `npm install`）
- xterm `Terminal` 替换 div：`ws output → term.write()`（ANSI 正确渲染），`term.onData → ws {type:'input'}`（键盘直达 PTY，含方向键/回车/ctrl-c/tab）
- FitAddon + ResizeObserver 自适应尺寸
- 协议与后端完全匹配，**后端 `proxy.py` 零改动**

**构建注意**：`frontend/Dockerfile` 用 `npm ci`（严格按 lock），加依赖必须同步更新 `package-lock.json`（本地 `npm install` 已做，不能只改 package.json）。

**待验证（上线前必测）**：
1. ASCII 二维码在 xterm 里的可扫性（字号/尺寸）。若扫不了：调 `fontSize` 放大，或用 hermes setup 自带 fallback（向导会 print `qr_url` 链接，复制到手机浏览器扫码）
2. `hermes` 命令不在 PATH（第 12 节），用全路径 `/opt/hermes/.venv/bin/hermes gateway setup`
3. 扫码建机器人不需 lark-oapi（纯 HTTP），但机器人收消息需要——扫完若报错，手动装 + 重启
4. resize（PTY 尺寸同步）MVP 未做，curses 用默认 80x24

**保留**：第 26 节的「复制命令弹窗」保留作备用入口。

---

## 归档 H — 对应原第 28 节：飞书接入验证流程详细步骤

### 验证通过的完整流程
1. 前端「实时终端」（xterm，第 27 节）连进用户容器
2. 跑 `/opt/hermes/.venv/bin/hermes gateway setup`（hermes 不在 PATH，第 12 节，必须全路径）
3. 平台列表**输数字 `2`** 选 Feishu（**不是方向键**，方向键会显示成 `^[[B`）→ 进 Feishu Setup → **输 `1`** 选 Scan QR code
4. device flow：没装 qrcode 时显示授权 URL（手机飞书打开确认）；装了 qrcode 显示 ASCII 二维码。授权后自动创建机器人，写 `FEISHU_*` 到 `/opt/data/.env`
5. 飞书里给机器人发 `/sethome` 设置 home channel（否则提示 No home channel）
6. 装消息依赖：`docker exec -u root <容器> bash -lc 'uv pip install --python /opt/hermes/.venv/bin/python "lark-oapi==1.5.3" "qrcode==7.4.2"'`
7. 重启容器 `docker restart <容器>` → gateway 加载飞书平台 + 连 websocket（日志见 `✓ feishu connected` + `connected to wss://msg-frontier.feishu.cn/...`）

### 踩到的两个坑（上线必修，都涉及重建 hermes 镜像）

**坑 1：前端终端是 root 用户 → setup 写 .env 所有者变 root → 容器重启崩溃循环**
- 现象：`chmod /opt/data/.env: Operation not permitted` + entrypoint `set -e` 退出 + `Restarting(1)` 循环
- 根因：`proxy.py:_start_hermes_terminal_socket` 的 exec_run 没指定 user，docker exec 默认 root
- 临时修复：`docker run --rm -v <hermes-data-xxx-home>:/data alpine chown -R 10000:10000 /data`（hermes uid=10000）
- **必修**：前端终端改以 hermes 用户执行（exec_run 加 `user="hermes"`），用户写文件即 hermes 所有。否则每个终端用户 setup 后重启必崩。改 `proxy.py` 一行 + 重建 gateway。

**坑 2：qrcode + lark-oapi 没预装进镜像**
- 没 qrcode → device flow 只显示 URL（非二维码），体验差
- 没 lark-oapi → 机器人收不了消息
- 当前：容器内手动 `uv pip install`（**重建会丢**）
- **必修**：`Dockerfile.bridge` 装 `.[feishu]` extra（`qrcode==7.4.2` + `lark-oapi==1.5.3` 预烧进镜像），重建 hermes 镜像。否则每个用户都要手动装。

---

## 归档 I — 对应第 30 节：镜像体积/重建性能 + 第 32 节：删用户孤儿卷

### 镜像与重建（第 30 节）
- 镜像 `nanobot-hermes-agent:latest` = 6.67GB（`config.py:53`，`manager.py:96-99`）。全家桶：python venv(`uv sync --extra all`) + chromium/Playwright + ffmpeg + node×3 + web/TUI + pandoc + docker-cli + build-essential。构建用 `Dockerfile.bridge`（非 Dockerfile）。
- 重建慢根因：`create_container` 的 `client.containers.run()`（`manager.py:738`，retry :743）每次从 6.67G 镜像全量实例化（28+ 层 overlay）+ hermes `gateway run` 冷启动（.venv/lazy_deps/gateway boot/起 18080）。触发：DockerNotFound(:826/851/876)、archived(:880)、`_container_matches_runtime` 不匹配(:841/858/888)。
- **关键机制**：`_container_matches_runtime`（`manager.py:165-179`）只比 env+entrypoint+cmd，**不比镜像版本** → rebuild 镜像不会自动触发容器重建，老容器钉旧镜像继续跑。推广新镜像须显式删旧容器走 `DockerNotFound→recreate`。
- 镜像构建慢：冷构建 ~4-5min py deps + npm×3 + playwright + uv sync（`build_base_image.sh` + `build_once.py` 缓解）。

### 删用户孤儿卷（第 32 节，2026-06-25 实操）
- `destroy_container`（`manager.py:960` "data volumes are preserved"）设计保留卷 → 删用户只清 DB+容器不清卷 → 每用户留 2 孤儿卷 `hermes-data-{前8}`(170B) + `-home`(/opt/data,370-585MB)。
- 本次清理：删 zhiyong+mason（用户 4→2），清 7 组孤儿卷 ~2.9GB + 2 孤儿容器。清理后仅 admin + 1@qq.com。
- **彻底删用户步骤**：①删 DB 各表（无级联，逐表按 user_id/id 删 `usage_records`/`audit_logs`/`runtime_runs`/`user_port_bindings`/`containers`/`users`）②`docker rm -f <容器>` ③`docker volume rm hermes-data-{前8} hermes-data-{前8}-home`（docker rm 不带 -v 不删命名卷）④验证 `docker volume ls | grep hermes-data`。
- 命名规则：容器 `hermes-user-{user_id前8}`（`config.py:60`）；卷 `hermes-data-{前8}`+`-home`（`config.py:61`，`manager.py:81-87`）。

---

## 归档 J — 对应第 33 节：飞书 device flow 网页化（已部署验证）

### 背景
第 28 节「前端终端跑 setup」被负责人否决——要求自动执行、用户不碰终端。改 device flow 网页化。

### 方案
复用 hermes device flow 端点（`accounts.feishu.cn/oauth/v1/app/registration`，纯 HTTP，不依赖 lark-oapi），platform 后端 httpx 调飞书，前端显示二维码+轮询。用户点一下 → 网页出二维码 → 手机扫 → 自动创建机器人 + 写 .env + 重启。

### 改动
- `platform/app/routes/proxy.py`：加 `/feishu/onboard/begin|poll|commit`（httpx 调飞书，参数照抄 `hermes-agent/gateway/platforms/feishu.py` 的 `_begin_registration`/`_poll_registration`）+ `/container/restart`
- `platform/app/container/manager.py`：`_build_hermes_env_file(preserve_vars)` + `_read_existing_hermes_env_channel_vars` + `_CHANNEL_ENV_PREFIXES`——重建保留 `FEISHU_*` 等渠道变量（根治第 1 节覆盖）
- `frontend/src/pages/Channels.tsx`：弹窗 device flow 状态机（idle→loading→showing→committing→success）+ `qrcode.react` + 轮询 useEffect
- `frontend/src/lib/api.ts`：`feishuOnboardBegin/Poll/Commit`

### 验证（workflow 4-agent adversarial）
device flow 参数 8 项 EXACT MATCH hermes 源码 ✓；commit 安全（sys.argv 无注入/hermes 用户写 .env 不崩/持久化）pass ✓；2 high（关弹窗轮询 leak + expire_in 未用）已修。begin 端点实测返回真 qr_url（user_code=GVV2-UD23）+ device_code ✓。

### 闭环验证（2026-06-25）✅
前端点接入 → 网页出二维码 → 手机飞书扫码 → device flow 自动创建机器人 → commit 写 FEISHU_* + 重启 → 机器人收发消息正常。全程网页不碰终端。`/sethome` 设 home channel。

### hermes 镜像
`Dockerfile.bridge` 装 `[feishu]` extra + PATH 加 venv/bin。2026-06-25 构建完成（`44a73741dfe5`，6.67GB，exit 0），验证 lark-oapi/qrcode OK + hermes 在 PATH + main-only 模板生效。rebuild 不自动触发容器重建（第 30 节），推广须删旧容器。gateway 启动慢 3-4 分钟（连 postgres + seed）。

---

## 归档 K — 对应第 34 节：rebase upstream 完成（2026-06-26）

### 操作
本地 main（第 33 节 device flow + xterm + 裁剪 + 构建共 3 commit：`6379a2147`/`d8cbf8108`/`49014ec4e`）rebase 到 `upstream/main`（johnson7788，含 PR#46 + 文件管理增强）。流程：临时分支 `rebase-upstream` 试验 → workflow 三方分析（3 文件 analyze+verify 对抗验证）→ 解冲突 → `git push --force-with-lease origin main`。结果：落后 upstream 0、领先 3 commit，本地功能 100% 保留。`main = origin/main = 49014ec4e`。

### 冲突解决（真冲突只 2 文件）
- `.dockerignore`：取本地版（含 upstream `./*md` + 本地裁 5 agent 模板块）
- `Dockerfile.bridge`：取 upstream 版（多 `/etc/profile.d/hermes.sh` login-shell PATH 增强）+ 行62 `.[all,feishu]`（保留本地飞书依赖）
- `proxy.py`：自动合并（本地 device flow 增量在新区域，upstream 改行 422 root→`/`，不重叠）
- 文件管理栈（`hermes_files.py`/`FileManager.tsx`/`openclaw_compat.py`）本地没改，自动取 upstream 双根版 → 白捡文件管理增强

### 作者相对我多了什么
`7691e77ab`（Johnson 06-26）文件管理增强——`is_hermes_absolute_request`/`normalize_hermes_absolute_path`/`_filemanager_root_script`/`_build_plain_archive`，即「从 `/` 浏览整个容器」+「单文件目录下载打包修复」。作者也合并了我的 PR#46（`93afd373c`+`5f791e981`）。

### 合并影响（代码合并 ≠ 运行生效）
- hermes 镜像 `44a73741dfe5`（06-25 19:06，含 feishu）是 rebase 前构建，缺 `/etc/profile.d`（锦上添花）
- gateway/frontend：rebase 后 `proxy.py`(+device flow) + `hermes_files.py`(双根) + `Channels/FileManager` 都变了，运行中是 06-25 版
- 文件管理双根已生效（2026-06-26 用户确认，gateway/frontend 已重建）
- 2@qq.com（`dedfb45b`）06-26 新建容器自动用新镜像 `44a737` 开箱即用；1@qq.com（`6524bcbf`）旧容器+卷已于 06-26 清除（账号保留）

### 偏离核实（2026-06-26）
①双前缀 bug 已随 rebase 整文件换 upstream 版消除（`removeprefix` 修复，实测单前缀 + 2@qq.com 容器无残留）；②敏感文件暴露未解决、双根后加剧（`.env`/`config.yaml`/`auth.json` 可见可删可改，upstream 只保护根目录）；③`/workspace` 死卷未变（manager.py 挂载 rebase 未碰），非 bug。

---

## 归档 L — 对应第 36 节：默认模型缺陷 + agent 文件下载修复（2026-06-29）

### ① 默认模型——设计缺陷（当前无故障，延后）
实测 DB `is_default=openai`、容器 config.yaml/env 均为 `openai/glm-5.1`，三者一致（`dedfb45b`）。**缺陷**：agent 实际模型 = `settings.default_model`（`manager.py:134` env / `:456` config.yaml），**不读 DB `is_default`** → 管理员改 DB 默认不影响 agent。`set_default_model`（`model_config.py:239`）只标 provider，多模型 provider 选不中具体 model。`get_default_model`（`:167`）无合格 provider 时回退 `settings.default_model`（裸名无 provider 前缀），前端徽章匹配不上。修复需 manager 改用 `get_default_model(db)` 或同步 settings（较大）。

### ② agent 文件下载 404——✅ 已修复验证
**根因**：agent 文件在 `/opt/data/profiles/main/workspace/uploads/`，agent 引用 `workspace/uploads/xxx`（hermes workspace 视角）。前端 `toDownloadPath`（`FileDownloadPlugin.tsx:81`）提取相对 `workspace/xxx` → 后端 `normalize_hermes_read_path`（`hermes_files.py:196`）相对分支拼 `/opt/data/workspace/xxx`（实测该目录空）→ `get_archive` 404。`_legacy_profile_fallback_path`（`:523`）只处理 `/opt/data/profiles/` 前缀反方向，不救。
**修复**：`normalize_hermes_read_path` 相对分支（`:164` 前）对 `workspace`/`workspace-` 开头补 `/`，走 `:166-169`（`/workspace`→`/opt/data/profiles/main/workspace`）。
**验证**：`read_file_from_hermes_container('hermes-user-dedfb45b','workspace/uploads/1782455746703-SKILL.md')` 返回 4768 bytes text/markdown ✅（修复前 404）。gateway 重建运行。
⚠️ memory 旧描述"双卷/agent 写 /workspace 卷"不准——/workspace 是空死卷（仅 platform-runtime.json），agent 实际写 `/opt/data/profiles/main/workspace/`。

---

## 归档 M — 批量归档：已解决/废弃/被超越的历史节（原 1/3/9/12/37/38）

> 2026-07-02 从 memory.md 归档。原 13.1/22/23/26/27/28/34 节细节已分别在归档 B/E/F/G/H/K，memory.md 直接删除未重复搬运。

### 原第 1 节：飞书 env 被 platform 擦除（✅ 已解决）
`_build_hermes_env_file` 重建时重写 `/opt/data/.env` 覆盖 `FEISHU_*`（`manager.py:419-465`）。已由 device flow + `preserve_vars` 根治（归档 J）。

### 原第 3 节：.dockerignore 排除 agent 模板（✅ 已修复）
`*.md`→`./*.md`，恢复 `deploy_copy/Agents/*/SOUL.md`。

### 原第 9 节：lark-oapi 不持久化（✅ 已解决）
`[feishu]` extra（`pyproject.toml:150`）原 Dockerfile 不装。已由 `Dockerfile.bridge:62` 装 `.[all,feishu]` 解决（归档 J/N）。

### 原第 12 节：hermes 不在 PATH（✅ 已修）
`Dockerfile.bridge:80` `ENV PATH` + `:83` `/etc/profile.d/hermes.sh`（login-shell 增强）。镜像演进：`44a737`(06-25) → `663bc167`(06-26) → v0.17.0 升级后 `f420a8260c0a`(07-02，归档 N)。老容器需删重建才用新镜像。issue #45。

### 原第 14 节：代码修改记录（并入此处，与原 3/12 去重）
`.dockerignore` `./*.md`（原第 3 节）；`Dockerfile.bridge:80` PATH（原第 12 节，构建用 Dockerfile.bridge 非 Dockerfile）。

### 原第 37 节：待办 合并 upstream v0.17.0（2026-06-29 评估，已被第 40 节执行）
upstream `a5bb1acc0`(06-27) = hermes v0.17.0 + VenusFennn preserve/xterm + CI + 文档清理。本地独有 SSO/device flow/裁剪/workdir。rebase 可行；必冲突 `Dockerfile.bridge`（v0.17.0 gosu/requirements vs 本地 `.[all,feishu]`→取 v0.17.0+加回 feishu）+ `.dockerignore`。风险：v0.17.0 breaking change→重建镜像+端到端重测；device flow/SSO 低（platform 层独立）。核实点：diff upstream `hermes-agent/gateway/platforms/feishu.py` 的 `_begin_registration`/`_poll_registration` 参数。**已由第 40 节落地完成（归档 N）**。

### 原第 38 节：技能 toggle 缺路由 + 嵌套 resolve NameError（✅ 已修复 PR#52）
① toggle 路由缺失：`set_skill_disabled_in_hermes_container`（`hermes_skills.py:695`）零引用，前端 `PUT /skills/{name}/toggle` 无对应路由→404→`SkillStore.tsx:135` catch 回弹，开关关不掉。② `_RESOLVE_SKILL_SCRIPT` 缺 `Path` import（`hermes_skills.py:100`）：脚本用 `Path(dirpath)`（:138）但头部只补 `import json,os,sys` 漏 `Path`。顶层技能走 direct 分支（`os.path.isdir` 命中）正常；**嵌套技能**（`autonomous-ai-agents/codex`）走 `os.walk` 用 Path→`NameError`→400，影响共用该脚本的 7 函数（toggle/delete/download/list/read/write/zip）对嵌套技能全 400。
**修复**：`openclaw_compat.py` +18（toggle 路由，`disabled = not req.enabled`）；`hermes_skills.py` +3（脚本头加 import，一次覆盖 7 函数）。真实 user `9c0d224f` 容器内调函数验证 codex toggle 双向 OK。upstream 同款 bug，**PR #52 已提**；私有库 main `1dc59acd2` 同步，gateway 重建生效。排查教训：手写脚本无意补 import 掩盖了 bug，最终靠「在 gateway 容器内用真实 user 直接调端点函数抓异常」才定位到 NameError。

---

## 归档 N — 对应第 40 节：合并 upstream v0.17.0 升级全过程（2026-07-01~02，旧服放弃→新服全链路打通 ✅）

### 根因（base seal vs bridge npm build 权限死结）
main 和 v0.17.0 的 base seal 策略根本不同：
- **main base**（`hermes-agent/Dockerfile`）：`chmod -R a+rX /opt/hermes && chown -R hermes .venv ui-tui node_modules`。`a+rX` 只加读+执行**不去写位**，源码 `COPY --chown=hermes` 原本 owner 可写 → base 里 web/ 仍 hermes 可写 → main bridge 即使只 chown .venv 也能 npm build。
- **v0.17.0 base**：`chown -R root:root /opt/hermes && chmod -R a+rX && chmod -R a-w` → 整棵树 root 只读。

昨天 codex 死结 = v0.17.0 base（全树 a-w）+ main 风格 bridge（只 chown .venv 没 chmod u+w）= base 全锁 + bridge 没解锁 = npm build 写 `.tmp` EACCES。**两套 seal 策略混用必死**。

### build 写入点全集（bridge npm build 必须能写）
`web/node_modules/.tmp/*.tsbuildinfo`（tsc）/ `web/node_modules/.vite/`（vite cache）/ **`hermes_cli/web_dist/`**（vite outDir，HERMES_WEB_DIST 指向，**不是 web/dist**；base root 生成、seal 不翻、不在 build context，是易漏的 root 残留）/ `ui-tui/dist/entry.js`。（main 时代的 sync-assets.mjs 在 v0.17.0 已移除，build 脚本只是 `tsc -b && vite build`，web/public 不再是写入点。）

### 最佳方案（workflow 4 方案对比后选定）
跳过 bridge build 复用 base dist → risky（bridge 本地 Terminal.tsx≠base 源码时 dist 不对应）；递归解锁 web+ui-tui → 能过但治标（chown -R web 含 node_modules 几分钟）；cache 重定向 /tmp → broken；**对齐 main seal（选中）**→ 治本（base 不锁、bridge 不卡），偏离最小（# LOCAL 标记），和 main 已验证行为一致。

### 落地改动（upgrade-v017 分支，2026-07-01 新服务器）
① **base seal**：删 v0.17.0 `chown root:root + chmod a-w`，改 `chmod -R a+rX + chown -R hermes .venv/ui-tui/node_modules`（对齐 main）。
② **bridge Dockerfile.bridge**：feishu extra 保留；base 用 main seal 后 `.venv/ui-tui` 已 hermes 可写，**root 残留两个：web/node_modules（npm install root 装）+ hermes_cli/（含 web_dist，base npm build 生成、COPY 无 --chown，hermes_cli 整树也 root）**。bridge `chown -R hermes web/node_modules + hermes_cli` 解锁（小源码树，不触 26 分钟遍历）。⚠️ **只 chown web/node_modules 会漏 web_dist，vite emptyOutDir 必 EACCES**（对抗审查抓到的 bug，第一版改漏了）。
③ **合并冲突**：Terminal.tsx 融合（xterm + 飞书扫码描述）；proxy.py 保留 `user="hermes"`（对齐 workdir=/opt/data）；.dockerignore/pyproject 自动合并保留本地。

### 新服务器构建环境坑（逐个排掉，**将来重建必参考**）
- **buildx 缺失**（docker.io 包不含）→ `apt install docker-buildx`（ubuntu universe）。
- **docker.io 拉不动** → daemon.json registry-mirrors（daocloud/1panel/unsee）+ 预拉 pin-sha 基础镜像（uv 走 `m.daocloud.io/ghcr.io` retag 成官方名，digest 要匹配 pin）。
- **github.com i/o timeout**（s6-overlay ADD）→ base Dockerfile ADD/curl URL 加 `ghfast.top/` 前缀（# LOCAL；ghproxy.com/mirror.ghproxy.com 不通，ghfast.top/gh-proxy.com 通）。
- **playwright chromium**：npmmirror 对 v0.17.0 新版 cft（149.0.7827.55）**404**（只 mirror 了 main 旧版）→ 回退 cdn.playwright.dev 直连（实测 ~40KB/s，114MB 约 30+ 分钟，慢但通）。
- **ubuntu 无 docker socket 权限** → 全程 `sudo docker`（或 `usermod -aG docker`）。
- **bridge P0：漏 chown hermes_cli/web_dist**（对抗审查 workflow 抓的，第一版 bridge 只 chown web/node_modules）→ vite outDir=../hermes_cli/web_dist + emptyOutDir:true 写 root 目录 EACCES。修：bridge 改 `chown -R hermes web/node_modules + hermes_cli`。教训：改动落地后必须对抗审查，别只看 base 端正确。
- **bridge pip3 install 默认 pypi.org 拉不动**（incomplete-download）→ compose/Dockerfile.bridge 传 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`（uv install 也用）。base 的 uv sync 走 .lock 不受影响。
- **云安全组只开 8000-9000**：前端系 3080/3081/3082 外部不可达 → compose override 追加 8180/8181/8182 映射（原端口保留内部）。访问：前端 8180 / 管理 8181 / 简化 8182 / gateway 9900 / postgres 9901。飞书回调 `.env` 改 IP+端口（FEISHU_CALLBACK_URL=:9900、FRONTEND_REDIRECT_URL=:8180）+ 飞书开放平台改重定向 URI。

### 镜像构建耗时（2026-07-01 新服实测）
总 ≈ **3h52m**：base 3h26m（大头 #30 `uv sync` 全 extra 92min + #27 playwright chromium 下载 53min，瓶颈是**网络**非算力）；bridge 25m（复用 base 缓存）。日志 `/tmp/base-build-v017.log`、`/tmp/bridge-build-v017.log`。旧服放弃（同类网络坑未排掉），新服成功靠的是镜像源/代理全配对。

---

## 归档 O：v0.17.0 升级 saga 收尾（原 memory.md 第 40/41 节，2026-07-02）

saga 已彻底完成：upstream v0.17.0 合入 + 端到端验证 + 代码 push origin + main 部署就绪 + PR #46-52 全 merged + 工作分支清理。仅剩 edge-tts 镜像重建待办（见「代做（核实）清单.md」）。核心排查知识已固化进 CLAUDE.md「hermes 容器排查约定」「排查纪律」。

### 原 40·合并 upstream v0.17.0：端到端验证通过 ✅ 升级成功
base seal 沿用 main（`chmod -R a+rX + chown -R hermes .venv/ui-tui/node_modules`），bridge `chown -R hermes web/node_modules + hermes_cli` + 保留 feishu extra。镜像 `hermes-base:14835fe0d0aa` 4.82GB + `nanobot-hermes-agent:f420a8260c0a` 7.08GB。旧服放弃（回 main `1dc59acd2`），新服成功（网络坑：registry-mirrors/ghfast/清华 pypi/playwright 直连）。compose 五服务全 healthy。访问 `http://58.87.64.156:8180`/`8181`/`8182`/`9900`。端到端验证 ✅：Kit.Zhou 注册→飞书接入（复用 `cli_aacf6b91097b1bdf`）→发消息→LLM 走公司 fj bigmodel 回复→飞书收到。遗留：①edge-tts lazy install ~4min（`Dockerfile.bridge` 已预装待重建）；②`model.provider` ✅已修；③ghfast/feishu 回调环境特定；④upgrade-v017 ✅已 push origin + 合 main + 分支清理。过程/构建坑见归档 N。

### 原 41·飞书端到端 + 三修复 + 日志源教训
- **hermes 业务日志在容器内 `/opt/data/logs/`（`gateway.log`/`agent.log`/`errors.log`），不在 `docker logs`**（只有启动 banner + `[Lark] connected`）。排查收发/LLM 必看文件日志（约定写 CLAUDE.md）。本次看 docker logs 误判"收不到消息"近 1 小时。
- **LLM provider**：`config.yaml` `model.provider: auto` + `openai/glm-5.1` 误路由 openrouter（无 key）→ 401。根因 `config.py:57` `dedicated_hermes_default_provider` 默认 `"custom"`，hermes 不认→fallback auto。✅已修：`docker-compose.override.yml` gateway env 加 `PLATFORM_DEDICATED_HERMES_DEFAULT_PROVIDER=platform-gateway`（env_prefix=PLATFORM_，config.py:127），不用改代码/重建镜像。
- **首条慢 = edge-tts lazy install ~4 分钟**（glm-5.1 单次 4-11s，非模型慢）。`Dockerfile.bridge` 预装 `edge-tts==7.2.7` 待重建。
- **commit 自动发欢迎 + 设 home channel**（`proxy.py` `_feishu_send_welcome_and_get_chat_id`）：用 open_id 发消息拿 P2P chat_id 写 `FEISHU_HOME_CHANNEL`，免 `/sethome`。`activate_status=2` 不阻止收发。
- **删用户彻底清理**：`docker rm -f hermes-user-<uid8>` + `docker volume rm hermes-data-<uid8> hermes-data-<uid8>-home` + DB DELETE 五表（containers/runtime_runs/usage_records/user_port_bindings/users）。
