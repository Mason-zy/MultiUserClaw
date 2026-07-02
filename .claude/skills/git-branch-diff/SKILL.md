---
name: git-branch-diff
description: 汇总本地仓库与各远程（origin/upstream/fork 等）的版本差距和文件差距。当用户说“检查本地和云端的区别/差距/版本差距”“本地和远程差多少”“有没有未推送/未 pull 的提交”“分支对比”“合并上游/rebase 前先看差距”“推之前看看会推什么”时使用。流程：确认本地状态（当前分支 / merge-rebase 进行中 / 工作树脏不脏）→ fetch 全部远程 → 各远程 vs 本地基准的领先/落后计数 + commit 列表 → 文件层面业务偏离面（三点 diff）→ 按模板汇总成中文报告。覆盖 merge-in-progress、detached HEAD、多远程、main/master 自动识别、三点 vs 两点 diff 语义等坑。
allowed-tools: Bash(git:*), Bash(bash:*), Read
---

# Git 分支对比

汇总本地仓库与各远程的**版本差距**（领先/落后多少 commit）和**文件差距**（业务偏离面），并给出“如果现在推送/合并会发生什么”的预判。

## 触发条件

- “检查本地和云端的区别 / 差距 / 版本差距”
- “本地和远程差多少”
- “有没有未推送 / 未 pull 的提交”
- “分支对比”
- “合并上游 / rebase 前先看差距”
- “推之前看看会推什么”

## 核心原则

- **先确认本地状态再说差距**：必须先看 `git branch --show-current` + `git status`，避免把 merge-in-progress / 工作树脏当成“代码丢失/回归”（见 [[verify-git-state-before-auditing]]，这条在 MultiUserClaw 连犯过两次）。
- **fetch 后再对比**：不 fetch 的对比是过期的 remote-tracking 快照。
- **区分版本差距和文件差距**：版本差距是 commit 计数，文件差距是真实改动面（rebase 冲突的战场）。
- **区分“全量合并”和“业务偏离”**：合并上游会带进成百上千文件，但真正的业务偏离面（三点 diff）通常只有几十个——后者才是 fork 要长期维护的。

## 执行流程

### Step 1：跑脚本拿原始数据（在仓库根目录）

```bash
bash .claude/skills/git-branch-diff/scripts/git-branch-diff.sh
```

脚本自动完成：①当前状态（含 merge/rebase/detached/脏工作树检测）→ ②`fetch --all --prune` → ③各远程领先/落后计数 + commit 列表（▲本地领先 / ▼落后）→ ④业务偏离面 stat。

可选参数：
- `--no-fetch`：不 fetch（用已有 remote-tracking refs，快但可能过期；刚 fetch 过时用）
- `--base <分支>`：指定本地基准（默认自动选 main→master→当前分支）
- `--remote <名字>`：只看某个远程（远程多时聚焦）
- `--ignore-remote <名字>`：额外忽略某个远程（可多次使用，追加到忽略列表）
- `--all-remotes`：不过滤，输出全部远程
- 默认忽略 `venus`；可通过环境变量 `GIT_BRANCH_DIFF_IGNORE="venus foo"` 覆盖默认列表，或用 `--all-remotes` 清空

### Step 2：补关键 commit 细节（脚本已给计数和短列表，>15 个时按需展开）

```bash
# 本地领先上游的 commit（你的业务改动）
git log --oneline <upstream>/<branch>..<base>
# 上游领先本地的 commit（你还没合的）
git log --oneline <base>..<upstream>/<branch>
```

### Step 3：按下面的报告模板把脚本输出汇总成中文报告

## 报告模板

```
# 本地 vs 云端 差距汇总

## 一、版本差距（本地 <base> = <short-hash>）
| 远程 | 库 | 最新 commit | 本地领先 | 云端领先 | 状态 |
|------|----|-------------|--------:|--------:|------|
（每行一个远程：✅同步 / ⚠️分叉 / 本地更新）

## 二、与 <上游> 的 commit 差距
- 本地领先 N 个：<一句话归类，如“飞书 SSO、技能切换、终端”>
- 上游领先 N 个：<列关键 commit，标注最重要的>

## 三、文件差距
### A. <工作区/某分支> vs <私有库 origin>（如果要推/合会带的量）
X files +Y/-Z，按顶层目录分布
### B. 本地业务偏离面（vs 上游，三点 diff）
X files +Y/-Z，按类别列表（后端 / 前端 / 测试 / 配置 / 构建）

## 四、当前状态一句话
- 已提交状态 = ?（本地 main = origin？有无未推送）
- 工作区 = ?（merge/rebase 中？脏？）
- 如果推送/合并会 ?
```

## 边界情形（脚本已处理，但要会解读）

- **merge / rebase / cherry-pick in progress**：脚本标 ⚠️。此时 HEAD 不变但有 staged/未提交的合并内容——版本差距看的是 HEAD（不含未提交合并），要单独说明“工作区 = HEAD + 未提交合并”。
- **detached HEAD**：`git branch --show-current` 返回空，脚本显示 `(detached HEAD)`，基准回退到 HEAD。
- **工作树脏**：脚本标 ⚠️。差距对比的是 commit，与未提交改动无关；如需看未提交改动另跑 `git status` / `git diff`。
- **无 upstream 远程**：业务偏离面跳过（脚本提示）。
- **不同项目主分支名不同**：脚本自动试 main → master。

## 常见误判（坑）

- ❌ 把 merge-in-progress 的 staged 改动当成“本地领先”——commit 计数看 HEAD，**不含未提交合并**。
- ❌ 把“全量合并上游的文件数”当成业务偏离面——要看**三点 diff**（`A...B` = merge-base 起的两侧差异），不是两点（`A..B`）或直接 `git diff A B`。脚本第 5 节用的是三点。
- ❌ 不 fetch 就对比——remote-tracking refs 是上次 fetch 的快照，会漏掉云端新推送。
- ❌ 混淆领先/落后方向——`git rev-list --left-right --count A...B` 输出是 `A领先 B领先`（左=前者）。脚本里“本地领先/落后”已对齐方向，直接用即可。
- ❌ 只看本地分支不看远程跟踪分支——`git log origin/main..main` 才是“未推送”，`git log main` 包含已推送的。

## 关联

- 核查代码/记忆前先确认 git 状态——见记忆 [[verify-git-state-before-auditing]]。
- 本项目（MultiUserClaw）有 4 个远程：`origin`（私有库）、`upstream`（johnson7788 上游）、`fork`（Mason-zy 公开）、`venus`（VenusFennn，默认排除；`--all-remotes` 可恢复）。基准是 `main`，业务偏离面对照 `upstream/main`。
