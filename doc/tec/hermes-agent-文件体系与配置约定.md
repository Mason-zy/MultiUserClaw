# Hermes Agent 文件体系与配置约定

> 来源：hermes-agent 代码（`/opt/hermes/agent/prompt_builder.py`、`/opt/hermes/agent/system_prompt.py`）、hermes-agent 内置 SKILL.md、官方文档 https://hermes-agent.nousresearch.com/docs/

Hermes Agent 是 Nous Research 开源的多平台 AI Agent 框架。以下梳理其核心文件体系在 MultiUserClaw 容器环境中的约定。

---

## 一、系统 Prompt 三层结构

Hermes 每次新会话（new run）构建一次 system prompt，分三层注入：

| 层 | 内容 | 来源 | 声明周期 |
|----|------|------|----------|
| **stable** | agent identity（SOUL.md）+ 工具指南 + skills prompt + 平台提示 | HERMES_HOME 的 SOUL.md | 读盘，跨 session 稳定 |
| **context** | 项目上下文（AGENTS.md / .hermes.md / CLAUDE.md / .cursorrules） | CWD 下的对应文件 | 依赖 CWD，随工作目录变化 |
| **volatile** | memory snapshot + USER.md profile + 外部 memory provider + 时间戳 | memories/ 等 | 每 session 刷新 |

> 三个部分拼接成一个 `_cached_system_prompt`，agent 存活期内不变——这是保持上游 prompt cache 的互操作设计。

代码入口：`system_prompt.py:build_system_prompt_parts()` → `build_system_prompt()` → `prompt_builder.py:build_context_files_prompt()`

---

## 二、Identity 层：SOUL.md（仅此一个）

**路径**：`$HERMES_HOME/SOUL.md`

**加载逻辑**（`prompt_builder.py:load_soul_md()`）：
- Hermes 启动时检查 `get_hermes_home() / "SOUL.md"`
- 存在 → 读入系统 prompt 的 stable tier（第一段，其他所有内容在它之后）
- 不存在 → fallback 到硬编码的 `DEFAULT_AGENT_IDENTITY`（通用 AI 助手身份）

**在 MultiUserClaw 容器中**：
- `HERMES_HOME = /opt/data`
- 容器初始化时 `profiles/main/SOUL.md` 被 gateway 激活为实际生效的 SOUL.md
- 根 `/opt/data/SOUL.md` 也是有效文件，但 profile 激活后有覆盖关系

**`--ignore-rules` 的作用**：跳过所有 project context files **和** SOUL.md identity，同时禁掉 user config、plugins、MCP servers。用于排查"是我的配置还是 Hermes 本身的问题"。

### IDENTITY.md 不是 Hermes 标准文件

- Hermes 代码中**零引用**
- 官网文档未提及
- 唯一有效的 identity 文件是 SOUL.md
- 如果你看到 IDENTITY.md，那是外部项目（OpenClaw / MultiUserClaw）的历史约定，不是 Hermes 原生

---

## 三、Project Context 层：优先级与发现规则

**First match wins** — 一旦命中就停，不叠加：

| 优先级 | 文件 | 发现策略 | 适用场景 |
|--------|------|----------|----------|
| 1 | `.hermes.md` / `HERMES.md` | **沿父目录上溯到 git root** | Hermes 专用分层规则（根 + 子包覆盖） |
| 2 | `AGENTS.md` / `agents.md` | **CWD 一层的 top-level**，不递归 | 跨 agent 可移植指令（Claude Code、Codex 共享） |
| 3 | `CLAUDE.md` / `claude.md` | CWD only | 同上，Claude 风格 |
| 4 | `.cursorrules` + `.cursor/rules/*.mdc` | CWD only | 从 Cursor 迁移 |

代码：`prompt_builder.py:build_context_files_prompt()` 按上述顺序逐个试 `_load_hermes_md()` → `_load_agents_md()` → `_load_claude_md()` → `_load_cursorrules()`，首个命中即返回。

### CWD 是什么？

- **CLI 模式**：用户启动 hermes 的目录
- **Gateway 模式**：`TERMINAL_CWD` 环境变量决定的路径；为空则 fallback 到 `os.getcwd()`（通常是 HERMES_HOME）
- **Profile 模式**：切换 profile 时 gateway 以 profile 对应 HERMES_HOME 为 CWD

**MultiUserClaw 容器中**：`TERMINAL_CWD` 通常为空（未配置），所以 CWD = `os.getcwd()` = `/opt/data`（HERMES_HOME）。

### 关于 AGENTS.md 的重要澄清

- AGENTS.md **只在 CWD（不是任何子目录或父目录）** 查找
- 不要把项目规则放在 `~/.hermes/AGENTS.md` — 只对那一个目录生效
- 需要跨 project 的 context → 用 SOUL.md（identity only）或安装 skill
- 多 agent 项目（Claude Code + Codex + Hermes）推荐 AGENTS.md，所有工具都认

---

## 四、Memory 层：MEMORY.md + USER.md

**路径**：`$HERMES_HOME/memories/`

| 文件 | 用途 | 构建方式 |
|------|------|----------|
| `MEMORY.md` | 长期记忆（知识、经验、已学到的内容） | agent 自主写入 + 用户手动编辑 |
| `USER.md` | 用户档案（偏好、习惯、风格） | agent 随交互积累 |

两者都在 `volatile` tier 注入，每 session 刷新。

**Profile 隔离**：profiles 有独立的 `profiles/{name}/memories/`，与根 `$HERMES_HOME/memories/` 互不干扰。

---

## 五、Profile 体系

Hermes 支持多 profile（`hermes profile create/use/list/delete`）：

```
$HERMES_HOME/profiles/{name}/
├── SOUL.md        # 独立 identity
├── memories/      # 独立记忆
├── skills/        # 独立技能
├── cron/          # 独立定时任务
├── sessions/      # 独立会话
├── workspace/     # 独立工作区
└── config.yaml    # 独立配置
```

**Profile 核心约定**（`profiles.py`）：
- 每个 profile 是完全独立的 HERMES_HOME（`profiles.py:4`）
- `_CLONE_CONFIG_FILES`：`config.yaml`、`.env`、`SOUL.md`（clone 时复制）
- `_CLONE_SUBDIR_FILES`：`memories/MEMORY.md`、`memories/USER.md`
- Profile clone 的记忆文件和 SOUL.md 同等重要——保证身份连续性

**MultiUserClaw 中**：
- 每个用户容器有一个 main profile（`profiles/main/`）
- 子 agent = 子 profile（`profiles/{agent_name}/`）
- 新建子 agent（前端创建）时默认不种子化 skills（目前如此）

---

## 六、Skills 路径差异

| 身份 | Skills 路径 | 说明 |
|------|-------------|------|
| 主 agent | `/opt/data/skills/` | HERMES_HOME 级，所有 profile 共享种子 |
| 子 agent | `/opt/data/profiles/{name}/skills/` | profile 级，空模板 |

---

## 七、文件大小限制

每个 context 文件 cap **20,000 字符**（`prompt_builder.py:_truncate_content()`）。
- 超出部分用 head + tail 截断（中间插入 `[...truncated...]` 标记）
- 可覆盖：`config.yaml` 的 `context_file_max_chars`，或模型 context window 自适应
- 大项目规则建议拆成多个 skill，不要挤在一个文件里

---

## 八、安全扫描

所有 context 文件加载前经过 threat-pattern 扫描器（`prompt_builder.py:_scan_context_content()`）。
- 匹配 prompt injection / promptware 的内容被替换为 `[BLOCKED: ...]`
- 只屏蔽内容不屏蔽文件——文件的其余部分仍然注入
- 扫描是加载侧的最后一关，不在磁盘上修改文件

---

## 九、MultiUserClaw 容器中文件实际布局（以 kit.zhou 为例）

```
/opt/data/                          ← HERMES_HOME + CWD
├── SOUL.md                          ← 通用 identity（gateway 模式可能被 profile 覆盖）
├── config.yaml                      ← 模型/工具/平台配置
├── .env                             ← 密钥/环境变量
├── AGENTS.md                        ← project context（CWD 加载，配置正确！）
├── memories/
│   ├── MEMORY.md                    ← 长期记忆
│   └── USER.md                      ← 用户档案
├── profiles/
│   └── main/
│       ├── SOUL.md                  ← 主 agent identity（实际生效！）
│       ├── memories/
│       │   ├── MEMORY.md            ← profile 长期记忆
│       │   └── USER.md              ← profile 用户档案
│       ├── skills/                  ← profile 技能
│       ├── cron/                    ← profile 定时任务
│       ├── sessions/                ← profile 会话（始终为空，session 统一在根 sessions/）
│       └── workspace/
│           └── knowledge/           ← 知识库（5 个 .md 文件）
├── skills/                          ← HERMES_HOME 级 skills
├── sessions/                        ← 统一 session 存储（不按 profile 分）
└── gateway_state.json               ← gateway 状态
```

---

## 十、常见误解更正

| 误解 | 事实 |
|------|------|
| IDENTITY.md 是 Hermes 标准文件 | ❌ 不在 Hermes 任何代码或文档中 |
| AGENTS.md 从 profile 目录加载 | ❌ 只从 CWD 加载（`/opt/data/AGENTS.md`） |
| SOUL.md 和 AGENTS.md 可以同时作为 project context | ❌ project context 是 first match wins，SOUL.md 单独作为 identity 注入 |
| `--ignore-rules` 只跳过 AGENTS.md | ❌ 跳过全部 project context + SOUL.md + user config + plugins + MCP |
| profiles/main/SOUL.md 不会被加载 | ❌ profile 激活时以 profiles/main 为 HERMES_HOME，SOUL.md 从那里读 |

---

---

## 附：飞书 Markdown 渲染限制（排查记录 2026-07-03）

**现象**：bot 回复内容正确但 markdown 不渲染（`**粗体**`、`# 标题`、列表等显示为原始字符）。

**根因**（`adapter.py:4377-4389`）：hermes 飞书适配器的 `_build_outbound_payload` 按以下优先级选择消息格式：

1. 含 markdown 表格 → `msg_type="text"`（**纯文本，所有格式丢失**）
2. 含 markdown 标记（标题/粗体/斜体/链接/列表等）→ `msg_type="post"`（飞书 post 格式，支持渲染）
3. 其他 → `msg_type="text"`

`_MARKDOWN_TABLE_RE = re.compile(r"^\|.*\|\n\|[-|: ]+\|", re.MULTILINE)` 检测到 markdown 表格即**整条消息降级为 text**。这是故意设计（代码注释：飞书 post 类型的 `md` 元素不支持表格渲染）。

**解决方案**：在 SOUL.md 中添加"飞书回复禁止使用 markdown 表格，改用缩进列表格式"的约束。这样回复不含表格 → 匹配 markdown hint → 发 post 格式 → 正常渲染。

_文档版本：2026-07-03。源：hermes-agent v0.17.0 代码 + 内置 SKILL.md v2.2.0_
