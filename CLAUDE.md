# MultiUserClaw 项目协作规则

## 记忆文件约定

- 「写到记忆文件」= 本项目 `.claude/memory.md`（项目分析/问题记录/方案评估都追加这里，末尾「关联记忆」章节前插入，编号连续）
- 不写到 `~/.claude/` 全局记忆，不散落到 `doc/`
- 待做/核实清单固定放项目根：`代做（核实）清单.md`

## L0 Config

test-cmd: pytest | test-all: pytest | doc-path: docs | worktree-symlinks:

## BAIME 流程

[baime](https://github.com/yaleh/baime) 驱动：看板 `backlog/`（B″ 16 状态列）→ `/feature-to-backlog <topic>`（Proposal/Plan 双轮 review → `Basic: Ready`）→ `/loop-backlog`（自治 worker，worktree 隔离 + DoD 验证 + merge）。监控 `backlog task list --plain` / `backlog browser`；停 loop `touch backlog/.loop-stop`（启动前确认无 active Monitor）。specs/proposals/plans 落 `docs/`，与项目自有 `doc/` 分离。

## 新功能改动量评估（合并上游友好）

fork 自 `johnson7788/MultiUserClaw`（upstream），定期 rebase/merge，必须控改动量降冲突面：

- **动工前评估**：列改动文件，标是否 upstream 高频改动区（`platform/app/routes/proxy.py`、`hermes-agent/` 核心、`docker-compose.yml`、前端公共组件/布局），给冲突风险（低/中/高）。
- **优先小而隔离**：落进新增文件/独立模块，别大范围重构或散点改 upstream 文件。
- **必改热点**：改动集中最小化，用 `# LOCAL: <说明>` / `// LOCAL:` 标记本地段，方便 rebase 识别移植。
- **高风险先报方案**：触及多 upstream 热点或大重构，先报方案和改动面确认，别直接开干。
- **可提 PR 优先上游**：通用 bugfix/增强按 upstream 能接受的方式做 PR（参考已提 #46/#47/#48），合并后少一份偏离。

## 写操作测试约定（防 FakeDb 盲点）

**Why**：`get_or_create_feishu_user` 原用 `db.flush()` 没 `commit`，user 有 id 但不持久化 → callback 发 JWT 但 `/me` 查不到 → 401 → 前端清 token 踢回登录。FakeDb 的 `flush`/`commit` 都是 no-op，单测 25/25 绿但 user 没进 DB，真容器才暴露。

**How**：FakeDb 记 `commit` 调用（`self.committed` flag）+ `refresh` 桩；至少一个测试**显式 `assert db.committed is True`**（不能只断言 `added`/`flushed`，flush 只在事务内生成 id 不持久化）；持久化敏感逻辑优先真 DB session（事务回滚 fixture / testcontainer）。

**反模式**：只测 `db.add(user)` + `db.flush()` 就当"建用户"通过。**mock 通过 ≠ 真 DB 持久化**。

## hermes 容器排查约定（日志源 + 飞书/LLM 坑）

**Why**：2026-07-02 排查"不回消息"看 `docker logs` 折腾近 1h，改 provider/删用户/猜 `activate_status=2` 全错——实际文件日志里消息一直正常处理（inbound→LLM→response 全通）。根因：**hermes 业务日志不进 stdout**。

- **排查 hermes（消息/LLM/回复）先看容器内 `/opt/data/logs/`**：`gateway.log`（inbound message / response ready / Sending response）、`agent.log`（conversation_loop / API call #N / provider / latency / cache）、`errors.log`。`docker logs`（stdout）只有启动 banner / skills sync / `[Lark] connected to wss` / api_server WARNING，**无任何业务消息**。监控同理：`docker exec <c> tail -f /opt/data/logs/gateway.log`，`docker logs -f` 无效。
- **`activate_status=2` 不阻止收发**——别当"收发失败"根因（实测 status=2 照常）。判断收发看 `gateway.log` 有没有 inbound / Sending response，不看 activate_status，不看 `chats` 列表（P2P 单聊不一定返回，可能空）。
- **LLM 401 多半是 `config.yaml` provider 路由错**：顶层 `model.provider: auto` + `model.default: openai/glm-5.1` 被 auto 误路由到内置 openrouter（无 key）→ `HTTP 401`。根治：`config.py:57` `dedicated_hermes_default_provider` 默认 "custom"（hermes 不认→fallback auto），override.yml 配 `PLATFORM_DEDICATED_HERMES_DEFAULT_PROVIDER=platform-gateway`（env_prefix `PLATFORM_` 见 `config.py:127`），走 gateway 代理 → 公司 fj bigmodel `fjbigmodel.fjdac.cn`。验证：`agent.log` 里 `provider=custom base_url=http://gateway:8080/llm/v1` = 对。
- **删用户彻底清理**：`docker rm -f hermes-user-<uid8>` + `docker volume rm hermes-data-<uid8> hermes-data-<uid8>-home`（`/workspace`+`/opt/data` 两卷）+ DB DELETE（`containers`/`runtime_runs`/`usage_records`/`user_port_bindings`/`users`，无 FK 按序删）。`admin.py` `DELETE /users/{id}/container` 只删容器不删 users 记录。
- **回复慢 ≠ 不回复**：首条消息冷启动 + agent 跑浏览器/工具时单条可达数百秒（实测「你好呀」251s，含 edge-tts==7.2.7 lazy_deps 现装 ~4min）。看 `agent.log` 的 `API call #N` / `tool ... completed` 判断跑工具还是真卡死。

**反模式**：看 `docker logs` 没消息就断定"收不到消息"然后瞎改。**先看 `/opt/data/logs/gateway.log` 再下结论**。

## 排查纪律（不许猜测，必须代码/日志核实）

**Why**：2026-07-02 飞书排查反复凭表面现象猜根因——"activate_status=2 所以不能收发"、"LLM 401 要改 manager 代码"——**全猜错**。实际是看错日志源 + 没查 settings 默认值（一行 env 就能修，不用改代码）。猜测导致误删用户、误改代码、误导用户近 1h。

- **下结论前必须用代码/日志证实**：说"X 是根因"前先 `grep`/`Read` 代码或看真实日志，给 `file:line` 或日志行作证据。**没有证据的因果陈述 = 猜测，禁止**。
- **禁止基于"空日志/某状态字段/应该是"下结论**：`docker logs` 空 ≠ "收不到消息"（业务日志在 `/opt/data/logs/`）；字段值（`activate_status` 等）不查文档/实测就断"不能用"；"应该是"不替代读代码。
- **配置类问题先查 setting 默认值 + env 注入链**：`config.py` 默认值 → `env_prefix`（`PLATFORM_`）→ compose `environment` 是否注入 → 容器实际 env。很多"bug"是默认值不合理或漏配 env，一行 .env/override 就能修，别急着改代码。
- **区分"已验证"和"推测"**：对用户标注哪个是日志/代码铁证、哪个是推测；推测的先核实再下结论，**别把推测当事实讲**。

**反模式**：看表面现象 → 脑补因果 → 直接建议改代码/删数据。**正确**：表面现象 → `grep`/`Read` 代码 + 真实日志 → 用证据下结论。
