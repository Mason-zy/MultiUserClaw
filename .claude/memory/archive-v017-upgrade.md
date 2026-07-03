---
name: multiuserclaw-archive-v017-upgrade
description: MultiUserClaw 记忆归档 — v0.17.0 升级全过程
metadata:
  type: project
---

# v0.17.0 升级全过程

来自  精简索引，详细过程/方案归档于此。按原名章节回溯即可。

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

