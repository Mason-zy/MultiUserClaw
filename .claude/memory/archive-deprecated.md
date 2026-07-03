---
name: multiuserclaw-archive-deprecated
description: MultiUserClaw 记忆归档 — 已完成的过时节归档
metadata:
  type: project
---

# 已完成的过时节归档

来自  精简索引，详细过程/方案归档于此。按原名章节回溯即可。

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

---
## 归档 P — 已完成历史节归档（原 memory.md 第 10/13/24 节，2026-07-03）

> 2026-07-03 从 memory.md 归档（已完成 / 历史对比，不再日常查阅）。memory.md 保留活问题与活知识。第 40/41 节内容已在归档 O，memory 侧删除（archive 不重复）。

### 第 10 节：纯 hermes vs MultiUserClaw（历史对比）
纯 hermes 接飞书一行永久生效；MultiUserClaw 需先解容器生命周期 × 渠道持久化冲突。

### 第 13 节：渠道配置全链路不可用（✅ ②③已解决）
原三层①UI空壳②env覆盖③依赖未预装。②③已由 `preserve_vars`+device flow 解决（第 33 节），仅①成立（第 2 节）。

### 第 24 节：只保留 main agent 模板（✅）
`.dockerignore` 排除 `deploy_copy/Agents/{manager,programmer,researcher,hr,doctor}/`。对新用户生效；老 profile 需手动清。

---
## 归档 Q — 代做清单 baime OCA 核实证据全集（2026-07-03）

> 代做（核实）清单.md 各条的 file:line / 命令 / 日志核实证据。清单侧只留精简 checkbox，详细证据在此。判定：✅真问题需改 / ❌描述过期 / ⚪无关影响。P0 安全已短期修复、TASK-3 三 bug 已修（commit 6c6ccefff）。

### CI/CD
- **根 CI 缺失** ✅P2：根 `.github/workflows/` 实测不存在；workflow 全在 `hermes-agent/.github/workflows/`（16 个）。
- **补根 workflow** ✅P2：配套，钉 node 22。
- **CI Node 版本** ✅P2：本机 `node v18.19.1`；`hermes-agent/package.json:43` `engines.node>=20`；三前端 Dockerfile `node:22-alpine`、hermes `node:22-bookworm-slim`。
- **CI 装 uv/pytest** ❌部分过期：`pytest` 已装 9.1.1（`/home/ubuntu/.local/bin/pytest`），只缺 `uv`。

### 部署脚本
- **端口统一** ✅P2：`deploy_docker.py:498` `args.gateway_port=8080`、`build_once.py:264` `--gateway-port default=8080`；compose `9900:8080`。
- **docker_result NameError** ✅P1 **已修 TASK-3**：原 `deploy_docker.py:118-123` 引用全文件 0 处赋值的 `docker_result`，删死分支+常量+误导提示。
- **--clean 前缀** ✅P1 **已修 TASK-3**：原 `:382` `openclaw-user-`（实测容器前缀 `hermes-user-`），改对。
- **override 拆分** ⚪：override 是 Compose 本地覆盖机制（自动合并），已 `# LOCAL:` 标记；L11 `PLATFORM_DEDICATED_HERMES_DEFAULT_PROVIDER=platform-gateway` 运行必需不能拆。仅 pgdata_new + 8180-8182 本机专配，低优。
- **build_once 端口同步** ✅P2：`:264` 默认 8080 未同步 9900。

### Docker 构建
- **npm ci** ✅P2：`manage_front/Dockerfile:9` 是 `npm install`（非 `npm ci`）。
- **PIP_INDEX ARG 生效** ✅P2：`platform/Dockerfile:5` ARG 在、`:17` 用 ARG，但 `:23` `--default-index https://pypi.tuna.tsinghua.edu.cn/simple` 硬编码，ARG 形同虚设。
- **ghfast.top 参数化** ✅P1 **已修 TASK-3**：原 `:70-73,81` 三处硬编码 `https://ghfast.top/https://github.com/`，改 `ARG GITHUB_MIRROR` + `${GITHUB_MIRROR}https://github.com/`。
- **bridge chown** ⚪：`Dockerfile.bridge:65` chown `web/node_modules` + `hermes_cli`，`:83-84` 补 `.venv`/`ui-tui`/`node_modules`，未遗漏。
- **edge-tts 镜像重建** ✅P1：commit `3e212d9ab`(2026-07-02 15:14) 晚于镜像 build(2026-07-01 21:09) 18h → 镜像不含 edge-tts。⚠️ 连带：重建必带 `--build-arg GITHUB_MIRROR=https://ghfast.top/`。
- **LLM provider** ✅已修 2026-07-02：`config.py:57` 默认 `custom`，override env `PLATFORM_DEDICATED_HERMES_DEFAULT_PROVIDER=platform-gateway`。

### 测试覆盖
- **conftest/README 默认端口** ✅P2：`conftest.py:40` + `README.md:10/30/37` 默认 `localhost:8080`（实际 9900）。
- **部署脚本单测** ⚪：真缺（`tests`/`platform/tests` grep `deploy_docker|build_once` 无匹配），先修脚本 bug 再补。
- **compose 一致性测试** ⚪：真缺，跟端口统一一起做。
- **e2e** ⚪：真缺，起完整栈成本高。
- **skip 用例** ✅P2：platform/tests 34 处 skip，16 处标 `requires DB mocking not implemented`（`test_hermes_runtime.py:590/637/674/714/1384/1723/1788/1841/1872/2371/2591/2780` + `test_hermes_compat.py:72`），应补 DB mock（写操作路径优先）。
- **写操作测试规则**：规则遵守项（FakeDb commit 约定），保持。

### 运维与安全
- **SSE/WS query token** ✅P0 **短期已修**：5+ 处 `?token=`（`api.ts:447`/`Terminal.tsx:50`/`Dashboard.tsx:102`/`NotificationProvider.tsx:142`/`FileDownloadPlugin.tsx:284,300`）；`docker logs openclaw-frontend` 实测完整 JWT 明文，8180 公网可达。短期 `frontend/nginx.conf` `access_log off` + rebuild。根治短期一次性 ticket / header。
- **文件下载/预览 token** ✅P0 **短期已修**：`FileDownloadPlugin.tsx:284` `window.open` 进浏览器历史/Referer；`:300` `<img src>` 带 query-token。`access_log off` 堵日志侧。
- **JWT_SECRET/PG 密码** ✅P0 **部分已修**：`config.py:13` 默认 `change-me-in-production`；`compose:45` `PLATFORM_JWT_SECRET: ${JWT_SECRET:-change-me-in-production}`。已修：`.env` 改 43 字符随机 + recreate gateway，容器内实测非默认。待做：PG 密码 `compose:19` 硬编码 `nanobot` 改 `${POSTGRES_PASSWORD:?}`。
- **CancelledError** ⚪：`docker compose logs gateway --tail 5000` CancelledError 13 条、"connection cleanup" 字样 0 条、无业务异常伴随，SSE 客户端断开时异步连接清理预期噪音。

### 技能版本管理（三条断言全准确，行号已校正）
- **version 不解析** ✅：`hermes_skills.py:177`（`_skill_frontmatter`）白名单 `{name,description}`；dogfood/computer-use/yuanbao SKILL.md 写 version。
- **dir_fingerprint 对外删** ✅：`:62-75` 算 SHA256、`:518` `if key != "fingerprint"` 删、去重在 `:504-512`。
- **git 不锁 commit + 无 update** ✅：`:599` `git clone --depth 1`、`:622-629` 缓存无 commit、`:633-678` 装完丢；`openclaw_compat.py` 路由 list(124)/delete(132)/download(142)/toggle(159)/upload(172)/search(182)/recommended(216)/recommended-install(233) 无 update。
- **zip 版本快照** ✅行号对：`_put_skill_archive` `311-337` `put_archive` 纯覆盖。

---

