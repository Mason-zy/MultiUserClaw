# MultiUserClaw 项目协作规则

## 记忆文件约定

当用户说「写到记忆文件」「记录到记忆文件」「存到记忆文件」时，统一指本项目内的：

```
.claude/memory.md
```

即 `/home/fjd/Project/MultiUserClaw/.claude/memory.md`。

- 所有项目分析、问题记录、方案评估都追加到这个文件
- 不要写到 `~/.claude/` 下的全局记忆，也不要散落在 `doc/` 等其他位置
- 追加内容时，在文件末尾的「关联记忆」章节之前插入新章节，保持编号连续

## L0 Config

test-cmd: pytest
test-all: pytest
doc-path: docs
worktree-symlinks:

## BAIME 流程

本项目使用 [baime](https://github.com/yaleh/baime) 方法论驱动开发：

- 看板：`backlog/`（B″ 16 状态列，已由 `/backlog-setup` 初始化）
- 新功能走 `/feature-to-backlog <topic>` → Proposal/Plan 双轮 review → `Basic: Ready`
- 执行走 `/loop-backlog`（自治 worker，worktree 隔离 + DoD 验证 + merge）
- 监控：`backlog task list --plain` 或 `backlog browser`
- 停止 loop：`touch backlog/.loop-stop`（启动前确认无 active Monitor）

Specs/proposals/plans 产物落在 `doc-path: docs`，与项目自有文档 `doc/` 分离。

## 新功能改动量评估（合并上游友好）

本项目 fork 自 `johnson7788/MultiUserClaw`（upstream），需要定期 rebase / merge upstream 改动。因此开发新功能时必须控制本地改动量、降低冲突面：

- **动工前先评估改动量**：列出改动文件清单，标注每个文件是否属于 upstream 高频改动区（尤其 `platform/app/routes/proxy.py`、`hermes-agent/` 核心模块、`docker-compose.yml`、前端公共组件 / 布局），给出冲突风险等级（低 / 中 / 高）。
- **优先小而隔离的改动**：新功能尽量落进新增文件或独立模块，避免大范围重构或散点修改 upstream 文件。
- **必改热点文件时**：改动集中、最小化，并用注释标记本地改动段（如 `# LOCAL: <说明>`、`// LOCAL:`），方便 rebase 时快速识别与移植。
- **高风险先报方案**：评估为高风险（触及多个 upstream 热点，或涉及大重构）时，先把方案和改动面报给我确认，不要直接开干。
- **可提 PR 的优先上游**：通用 bugfix / 增强优先按 upstream 能接受的方式做成 PR 提给作者，合并后本地就少一份偏离（参考已提的 PR #46/#47/#48）。

## 写操作测试约定（防 FakeDb 盲点）

**Why**：TASK-1 的 `get_or_create_feishu_user` 原先用 `db.flush()` 没 `commit`，user 对象有 id 但**不持久化** → callback 发了 JWT 但 `/me` 查不到 user → 401 → 前端清 token 踢回登录页。FakeDb mock 的 `flush`/`commit` 都是 no-op，单元测试 25/25 绿但 user 根本没存进 DB，真容器里才暴露。

**How to apply**：
- 写操作（INSERT/UPDATE/DELETE）的单元测试，FakeDb 必须记录 `commit` 调用（`self.committed` flag），并提供 `refresh` 桩。
- 至少一个测试**显式断言 `assert db.committed is True`**，不能只断言 `db.added` / `db.flushed`（flush 只在事务内生成 id，不持久化）。
- 持久化敏感的逻辑优先用真 DB session 测（事务回滚 fixture / testcontainer），FakeDb 只做快速逻辑验证。

**反模式**：只测 `db.add(user)` + `db.flush()` 就认为"建用户"通过。**mock 通过 ≠ 真 DB 持久化**。
