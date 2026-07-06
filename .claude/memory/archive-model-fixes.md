---
name: multiuserclaw-archive-model-fixes
description: MultiUserClaw 记忆归档 — 模型缺陷与功能修复
metadata:
  type: project
---

# 模型缺陷与功能修复

来自  精简索引，详细过程/方案归档于此。按原名章节回溯即可。

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

---
## 归档 R — vision 配置 + audit_log + baime 流程（2026-07-03）

### 46. vision 配置注入（✅ 已修复，commit a289786）

**Why**：hermes 容器 config.yaml 无 auxiliary 段 → vision auto 链（`auxiliary_client.py:4625`）因 DeepSeek 无 vision + 无 OpenRouter/Nous 凭证全 None → `RuntimeError`。飞书图无法识图。

**修复过程**：
1. 实测 fjbigmodel vision：glm-5.1 ✅ / glm-5.2 ✅（经 gateway fallback）/ gpt-5.4/5.5 ❌。选 openai/glm-5.1（必须 `openai/` 前缀，`proxy.py:128` 按 `/` 切 provider，裸名 fallback → default deepseek 无 vision）。
2. 实测 gateway 端到端：`Bearer <真实token> + openai/glm-5.1 + 图片` ✅。
3. `_build_hermes_config_yaml()` 加 auxiliary.vision。**第一版 bug**：api_key 写死 "platform-proxy" → 401。修复 a289786：api_key 从基础函数移除，`_write_hermes_runtime_files(container)` 从容器 env `NANOBOT_PROXY__TOKEN` 读每容器唯一 token 注入。
4. 存量 3 容器手改 config.yaml（取 `custom_providers[platform-gateway]` 真实 token）。新容器自动带。
5. 测试 10/10 pass。

### 47. audit_log 双写修复（✅ 代码 merge，⏳ 待 gateway 重建镜像）

**Why**：`service.py` LiteLLM 路径 `_record_usage`（:557 已写）之后又写 `write_audit_log`（:770-781 流式 + :801-812 非流式）→ 2 audit_log/调用。Anthropic（:664）干净。

**修复**：删两处冗余 + `db.commit()`，`# LOCAL` 标记。新测试断言 `write_audit_log` count=1。9/9 pass。Merge 到 main（3e7412b/6eee85d）。⏳ gateway 代码 bake 进镜像，需 `docker compose build gateway && up -d --force-recreate`。

### 48. baime feature-to-backlog + loop-backlog 全流程实战

两 task 跑通全流程（Proposal 5 自审 → Plan 9 合规 + 代码复核 → finalise → daemon → claim → worktree → Agent 并行实现 → poll → pre-merge DoD → serial merge → 清理）。踩坑：① `~/.local/share/baime` 被删 → skill 不注册，跑 `install.sh` + 重启修复；② TASK-2 Agent API Error 中断，worker 接手完成。
