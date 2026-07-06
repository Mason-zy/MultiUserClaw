---
name: multiuserclaw-memory-index
description: MultiUserClaw 记忆归档目录索引——从 memory.md 精简下来的详细过程，按主题分片
metadata:
  type: project
---

# 记忆归档索引

> `memory.md` 只存精简摘要 + `file:line` + 状态。详细过程、方案评估、验证步骤、架构图见本目录下的主题文件。

| 文件 | 内容 | 包含归档 |
|------|------|------|
| `archive-feishu-channel.md` | 飞书渠道：手动配置、扫码方案、device flow 网页化、接入验证 | B, E, F, H, J |
| `archive-platform-infra.md` | 终端 PTY、profile 目录、模型 UI 架构、xterm 升级、镜像构建、孤儿卷、rebase | A, C, D, G, I, K |
| `archive-model-fixes.md` | vision 配置注入、audit_log 双写、baime 全流程实战 | L, R |
| `archive-v017-upgrade.md` | v0.17.0 升级全过程 + saga 收尾 | N, O |
| `archive-deprecated.md` | 已解决/废弃/被超越的历史节 + 代做清单核实证据 | M, P, Q |

**如何用**：需要回溯详细过程时，按主题打开对应的 `archive-*.md` 文件。每个归档节都标了原 memory.md 节号（如「归档 A — 对应原第 11 节」），方便对照。
