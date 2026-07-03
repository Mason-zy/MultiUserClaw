---
name: multiuserclaw-archive-feishu-channel
description: MultiUserClaw 记忆归档 — 飞书渠道接入完整链路
metadata:
  type: project
---

# 飞书渠道接入完整链路

来自  精简索引，详细过程/方案归档于此。按原名章节回溯即可。

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

