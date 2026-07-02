#!/usr/bin/env bash
# git-branch-diff.sh — 汇总本地仓库与各远程的版本/文件差距（原始数据）。
#
# 用法:
#   git-branch-diff.sh                 # 默认: fetch --all + 全远程对比
#   git-branch-diff.sh --no-fetch      # 不 fetch（用已有 remote-tracking refs，快但可能过期）
#   git-branch-diff.sh --base dev      # 指定本地基准分支（默认自动选 main→master→当前）
#   git-branch-diff.sh --remote upstream  # 只看某个远程
#   git-branch-diff.sh --ignore-remote venus  # 额外忽略某个远程（默已忽略 venus）
#   git-branch-diff.sh --all-remotes   # 不过滤，输出全部远程
#
# 输出原始数据；由 SKILL.md 指导汇总成中文报告。

set -uo pipefail

DO_FETCH=1
BASE=""
ONLY_REMOTE=""
# LOCAL: 默认忽略 venus；可用 GIT_BRANCH_DIFF_IGNORE 环境变量覆盖，或用 --ignore-remote/--all-remotes 调整
IGNORE_LIST="${GIT_BRANCH_DIFF_IGNORE:-venus}"

filter_remotes() {
  # 从空格分隔的远程列表中移除 IGNORE_LIST 里的远程
  local input="$1"
  local output=""
  for r in $input; do
    case " $IGNORE_LIST " in
      *" $r "*) ;;
      *) output="$output $r" ;;
    esac
  done
  echo "$output"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --no-fetch) DO_FETCH=0; shift;;
    --base)     BASE="$2"; shift 2;;
    --remote)   ONLY_REMOTE="$2"; shift 2;;
    --ignore-remote) IGNORE_LIST="$IGNORE_LIST $2"; shift 2;;
    --all-remotes)   IGNORE_LIST=""; shift;;
    -h|--help)  sed -n '2,14p' "$0"; exit 0;;
    *) echo "未知参数: $1（见 --help）" >&2; exit 2;;
  esac
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ 不在 git 仓库内" >&2; exit 1; }
REPO=$(git rev-parse --show-toplevel)
GIT_DIR=$(git rev-parse --git-dir)

SEP="================================================================"
echo "$SEP"
echo "  Git 分支对比 · $(basename "$REPO")"
echo "$SEP"

# ── 1. 当前状态 ──────────────────────────────────────────────
echo ""
echo "## 1. 当前状态"
CUR_BRANCH=$(git branch --show-current 2>/dev/null)
[ -z "$CUR_BRANCH" ] && CUR_BRANCH="(detached HEAD)"
echo "当前分支: $CUR_BRANCH"
echo "HEAD:     $(git rev-parse --short HEAD) · $(git log -1 --format='%s (%cr)' HEAD 2>/dev/null)"

warn=""
git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1 && warn="$warn  ⚠️ MERGE IN PROGRESS (MERGE_HEAD=$(git rev-parse --short MERGE_HEAD))\n"
{ [ -d "$GIT_DIR/rebase-merge" ] || [ -d "$GIT_DIR/rebase-apply" ]; } && warn="$warn  ⚠️ REBASE IN PROGRESS\n"
[ -d "$GIT_DIR/CHERRY_PICK_HEAD" ] && git rev-parse -q --verify CHERRY_PICK_HEAD >/dev/null 2>&1 && warn="$warn  ⚠️ CHERRY-PICK IN PROGRESS\n"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  warn="$warn  ⚠️ 工作树有未提交改动\n"
else
  echo "✅ 工作树干净"
fi
[ -n "$warn" ] && printf "%b" "$warn"

# 计算并过滤远程列表，供后续所有对比复用
RAW_REMOTE_LIST=$(git remote)
REMOTE_LIST="$RAW_REMOTE_LIST"
if [ -n "$ONLY_REMOTE" ]; then
  REMOTE_LIST="$ONLY_REMOTE"
else
  REMOTE_LIST=$(filter_remotes "$REMOTE_LIST")
fi

# 提示被忽略的远程
if [ -z "$ONLY_REMOTE" ] && [ -n "$IGNORE_LIST" ]; then
  ignored=""
  for r in $RAW_REMOTE_LIST; do
    case " $REMOTE_LIST " in
      *" $r "*) ;;
      *) ignored="$ignored $r" ;;
    esac
  done
  [ -n "$ignored" ] && echo "（已忽略: $(echo "$ignored" | sed 's/^ //')；用 --all-remotes 查看）"
fi

# ── 2. fetch ─────────────────────────────────────────────────
if [ "$DO_FETCH" = 1 ]; then
  echo ""
  echo "## 2. fetch 所有远程"
  if git fetch --all --prune --quiet 2>"$GIT_DIR/.gb-fetch-err"; then
    echo "✅ fetch 完成"
  else
    echo "⚠️ fetch 有错误（可能部分远程不可达）:"
    sed 's/^/   /' "$GIT_DIR/.gb-fetch-err" 2>/dev/null
    echo "   （继续用已有 remote-tracking refs 对比）"
  fi
  rm -f "$GIT_DIR/.gb-fetch-err" 2>/dev/null
fi

# ── 3. 基准分支 ──────────────────────────────────────────────
if [ -z "$BASE" ]; then
  for cand in main master; do
    if git show-ref -q --verify "refs/heads/$cand" 2>/dev/null; then BASE="$cand"; break; fi
  done
fi
[ -z "$BASE" ] && BASE="${CUR_BRANCH/\(detached HEAD\)/HEAD}"
echo ""
echo "## 3. 本地基准分支: $BASE"

# ── 4. 各远程领先/落后 ───────────────────────────────────────
echo ""
echo "## 4. 各远程 vs 本地 $BASE"
# REMOTE_LIST 已在第 1 节后计算并过滤；--remote 已覆盖为单一远程
for r in $REMOTE_LIST; do
  echo ""
  echo "---- $r ----"
  echo "  URL: $(git remote get-url "$r" 2>/dev/null)"
  # 候选远程分支：远程 HEAD + main + master（去重、仅取存在的）
  remote_head=$(git symbolic-ref "refs/remotes/$r/HEAD" 2>/dev/null | sed "s|refs/remotes/$r/||")
  seen=""
  candidates=""
  for c in "$remote_head" main master; do
    [ -z "$c" ] && continue
    case " $seen " in *" $c "*) ;; *) seen="$seen $c"; candidates="$candidates $c";; esac
  done
  for rb in $candidates; do
    ref="refs/remotes/$r/$rb"
    git show-ref -q --verify "$ref" 2>/dev/null || continue
    echo "  [$rb] $(git log -1 --format='%h %s (%cr)' "$ref" 2>/dev/null)"
    counts=$(git rev-list --left-right --count "$BASE...$ref" 2>/dev/null) || continue
    ahead=$(echo "$counts" | awk '{print $1}')
    behind=$(echo "$counts" | awk '{print $2}')
    echo "       本地 $BASE 领先 $ahead / 落后 $behind"
    # 简短 commit 提示（领先≤15 个时列出）
    if [ "${ahead:-0}" -gt 0 ] && [ "${ahead:-0}" -le 15 ]; then
      git log --oneline "$ref..$BASE" 2>/dev/null | sed 's/^/       ▲ /'
    fi
    if [ "${behind:-0}" -gt 0 ] && [ "${behind:-0}" -le 15 ]; then
      git log --oneline "$BASE..$ref" 2>/dev/null | sed 's/^/       ▼ /'
    fi
  done
done

# ── 5. 文件差距（业务偏离面，三点 diff）──────────────────────
echo ""
echo "## 5. 文件差距（业务偏离面）"
UPSTREAM=""
# REMOTE_LIST 已过滤忽略列表，避免 venus 等被误当 upstream
for r in $REMOTE_LIST; do case "$r" in upstream) UPSTREAM="upstream"; break;; esac; done
if [ -z "$UPSTREAM" ]; then
  for r in $REMOTE_LIST; do case "$r" in origin|fork) ;; *) UPSTREAM="$r"; break;; esac; done
fi

if [ -z "$UPSTREAM" ]; then
  echo "  （未找到上游远程，跳过业务偏离面）"
else
  urb=""
  for c in main master; do
    git show-ref -q --verify "refs/remotes/$UPSTREAM/$c" 2>/dev/null && { urb="$c"; break; }
  done
  if [ -z "$urb" ]; then
    echo "  （$UPSTREAM 下未找到 main/master 分支，跳过）"
  else
    echo "  vs $UPSTREAM/$urb （三点 diff = merge-base 起本地 $BASE 侧独有改动）:"
    git diff --shortstat "$UPSTREAM/$urb...$BASE" 2>/dev/null | sed 's/^/    /'
    echo ""
    echo "  文件清单:"
    git diff --stat "$UPSTREAM/$urb...$BASE" 2>/dev/null | sed 's/^/    /' | head -60
  fi
fi

echo ""
echo "$SEP"
echo "  原始数据输出完毕 → 按 SKILL.md 报告模板汇总成中文报告。"
echo "$SEP"
