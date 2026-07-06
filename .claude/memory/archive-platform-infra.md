---
name: multiuserclaw-archive-platform-infra
description: MultiUserClaw 记忆归档 — 平台架构、部署与升级
metadata:
  type: project
---

# 平台架构、部署与升级

来自  精简索引，详细过程/方案归档于此。按原名章节回溯即可。

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

### 2026-07-06 docker root 迁 500G 数据盘（#50）

系统盘 vda 50G 紧（65%）→ 数据盘 vdb 500G（`/opt/applications`，3% 用）。docker + containerd 都迁 `/opt/applications/data/`。

**踩坑**：docker 用 containerd snapshotter（`docker info` 的 `driver-type: io.containerd.snapshotter.v1`），**镜像层在 `/var/lib/containerd`（18G），不在 `/var/lib/docker`（793M metadata）**。第一次只迁 docker，启 docker 用新 data-root 后镜像层丢（回滚发现）。**必须连 containerd 一起迁**。

**步骤**：① 备份 daemon.json + `systemctl cat containerd` ② 停 `docker docker.socket containerd` ③ `rsync -aP /var/lib/{docker,containerd}/ /opt/applications/data/{docker,containerd}/` ④ docker `daemon.json` 加 `"data-root": "/opt/applications/data/docker"` ⑤ containerd systemd override `/etc/systemd/system/containerd.service.d/override.conf`：`ExecStart=/usr/bin/containerd --root=/opt/applications/data/containerd`（无 config.toml，socket 仍 `/run/containerd`）⑥ daemon-reload + 启 containerd + docker → 8 容器 unless-stopped 自动恢复。

**验证**：`docker info` Root Dir 新路径 + 镜像 15 个完整 + 8 容器 Up + postgres healthy + 卷挂载指数据盘 + gateway/hermes 功能正常。

**待做**：旧 `/var/lib/{docker,containerd}` 观察稳定后删腾系统盘 ~30G。

**收益**：build hermes 镜像不怕磁盘满（根治上次 build 崩系统：系统盘满 → postgres 写失败 → 连锁崩）。

**build arg 三件套**（`Dockerfile:31/32/66`，不传走官方源 CN 慢/挂）：`GITHUB_MIRROR=https://ghfast.top/`（s6-overlay）+ `APT_DEBIAN_MIRROR=https://mirrors.ustc.edu.cn/debian` + `APT_SECURITY_MIRROR=https://mirrors.ustc.edu.cn/debian-security` + `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。build 不影响运行容器（锁定旧镜像 ID，不跟 latest tag）。

---

