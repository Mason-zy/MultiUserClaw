---
task_id: kit-zhou-external-knowledge-bot
title: 改造 kit.zhou hermes 容器为对外知识解答机器人
status: Basic: In Progress
created: 2026-07-03
---

## Proposal

将 Kit.Zhou（`hermes-user-ce545995`）的 hermes 容器从"老板私人 AI 助手"改造为同时面向外部用户的知识解答机器人，回答 hosting 平台、AgentGateway、A2A 接入、agw CLI、baime 方法论 5 大领域问题，只依据知识库 `/opt/data/profiles/main/workspace/knowledge/` 的 5 个文件作答，不编造。

## Plan

**范围**：容器内 4 个文件，不动工具集、不重启、下条消息生效。

**改动清单**：

1. **IDENTITY.md**（新建 `profiles/main/IDENTITY.md`）— 保留私人助手定位 + 增补对外知识解答定位 + 5 大知识库主题表
2. **AGENTS.md**（新建 `profiles/main/AGENTS.md`）— 对外解答模式（独立运行不调度）+ 安全守则（不泄露路径/凭证/容器结构/内部架构）
3. **SOUL.md**（`profiles/main/SOUL.md` 已含知识库优先原则 + 对外定位，已就位 ✅）
4. **MEMORY.md**（两处已就位 ✅）— 知识库索引表 + 检索硬约束

## DoD

- [ ] `profiles/main/IDENTITY.md` 存在且含 5 大主题
- [ ] `profiles/main/AGENTS.md` 存在且含安全守则
- [ ] `profiles/main/SOUL.md` 含知识库优先原则 ✅
- [ ] `/opt/data/memories/MEMORY.md` 含索引 ✅
- [ ] `profiles/main/memories/MEMORY.md` 含索引 ✅
