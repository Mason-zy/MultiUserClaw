#!/usr/bin/env python3
"""
OpenClaw 一键升级脚本
从本地已 clone 的上游 OpenClaw 仓库同步文件到当前项目目录。
会尊重 .gitignore 规则，保护自定义新增文件，删除操作逐个确认。
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from fnmatch import fnmatch

# 我们新增的文件/目录，不应被上游覆盖或删除
CUSTOM_FILES = {
    "bridge",
    "bridge-entrypoint.sh",
    "bridge-package.json",
    "bridge-deploy-copy",
    "Dockerfile.bridge",
    "tsconfig.bridge.json",
    "upgrade_openclaw.py",
    "requirements.txt"
}


def load_gitignore_patterns(project_dir: Path) -> list[str]:
    """从 .gitignore 读取忽略规则"""
    gitignore = project_dir / ".gitignore"
    patterns = []
    if gitignore.exists():
        for line in gitignore.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """检查路径是否匹配 .gitignore 规则"""
    parts = rel_path.split("/")
    for pattern in patterns:
        clean = pattern.rstrip("/")
        # 带 ** 的模式
        if "**" in clean:
            simple = clean.replace("**/", "").replace("/**", "")
            for part in parts:
                if fnmatch(part, simple):
                    return True
            if fnmatch(rel_path, clean):
                return True
            continue
        # 检查目录名或文件名匹配
        if clean.startswith("/"):
            # 根目录相对匹配
            if fnmatch(rel_path, clean.lstrip("/")):
                return True
        else:
            # 任意层级匹配
            for part in parts:
                if fnmatch(part, clean):
                    return True
            if fnmatch(rel_path, clean):
                return True
    return False


def is_custom(rel_path: str) -> bool:
    """检查是否为我们自定义新增的文件/目录"""
    top = rel_path.split("/")[0]
    return top in CUSTOM_FILES or rel_path in CUSTOM_FILES

# 构建产物目录，遍历时直接跳过（避免 Windows 长路径报错）
SKIP_DIRS = {"node_modules", "dist", "dist-runtime", ".turbo", ".cache"}

def collect_files(root: Path, gitignore_patterns: list[str]) -> dict[str, Path]:
    """收集目录下所有文件（排除 .gitignore 匹配项、.git 和构建产物目录）"""
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过 .git 和构建产物目录（原地修改 dirnames 阻止递归进入）
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != ".git"]
        for fname in filenames:
            full = Path(dirpath) / fname
            rel = str(full.relative_to(root)).replace("\\", "/")
            if is_ignored(rel, gitignore_patterns):
                continue
            files[rel] = full
    return files

def check_git_clean(project_dir: Path) -> bool:
    """检查工作目录是否有未提交的更改"""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True, text=True
        )
        return result.stdout.strip() == ""
    except Exception:
        return True  # 如果不是 git 仓库，跳过检查

def files_are_identical(file1: Path, file2: Path) -> bool:
    """比较两个文件内容是否相同"""
    try:
        return file1.read_bytes() == file2.read_bytes()
    except Exception:
        return False

def confirm(prompt: str) -> bool:
    """请求用户确认"""
    return True
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False

def main():
    parser = argparse.ArgumentParser(description="升级 OpenClaw 到最新版本")
    parser.add_argument(
        "upstream_path",
        help="本地已 clone 的上游 OpenClaw 仓库路径，例如 /Users/admin/git/openclaw"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览变更，不执行实际操作"
    )
    parser.add_argument(
        "--use-gitignore",
        action="store_true",
        help="使用 .gitignore 规则过滤文件（默认不使用，会同步所有文件）"
    )
    args = parser.parse_args()

    upstream_dir = Path(args.upstream_path).resolve()
    project_dir = Path(__file__).parent.resolve() / "openclaw"

    if not upstream_dir.exists():
        print(f"错误: 上游目录不存在: {upstream_dir}")
        sys.exit(1)

    if not (upstream_dir / "package.json").exists():
        print(f"错误: {upstream_dir} 不像是一个有效的 OpenClaw 仓库")
        sys.exit(1)

    # ========== 打印说明 ==========
    print("=" * 60)
    print("  OpenClaw 升级工具")
    print("=" * 60)
    print()
    print(f"  上游仓库: {upstream_dir}")
    print(f"  本地项目: {project_dir}")
    print()
    print("  ⚠️  升级前请确保:")
    print("    1. 已提交所有本地更改 (git add && git commit)")
    print("    2. 已备份重要数据 (建议 git stash 或新建分支)")
    print("    3. 上游仓库已 git pull 到最新版本")
    print()
    print("  以下自定义文件/目录将被保护，不会被修改或删除:")
    for f in sorted(CUSTOM_FILES):
        print(f"    - {f}")
    print()

    if not check_git_clean(project_dir):
        print("  ⚠️  警告: 当前项目目录有未提交的更改!")
        print("  建议先执行 git commit 再继续。")
        print()

    if not confirm("是否继续升级?"):
        print("已取消。")
        sys.exit(0)

    # ========== 收集文件 ==========
    print("\n正在分析文件差异...\n")

    # 默认不使用 .gitignore，只有当 --use-gitignore 参数指定时才使用
    if args.use_gitignore:
        print("ℹ️  已启用 --use-gitignore，将使用 .gitignore 规则过滤文件\n")
        gitignore_patterns = load_gitignore_patterns(project_dir)
    else:
        print("ℹ️  默认模式：忽略 .gitignore 规则，将同步所有文件（包括 pnpm-lock.yaml 等）\n")
        gitignore_patterns = []

    upstream_files = collect_files(upstream_dir, gitignore_patterns)
    local_files = collect_files(project_dir, gitignore_patterns)

    # 分类变更
    to_add = []      # 上游新增
    to_update = []   # 上游修改
    to_delete = []   # 上游已删除（本地多余）

    for rel, upstream_path in sorted(upstream_files.items()):
        if is_custom(rel):
            continue
        if rel not in local_files:
            to_add.append(rel)
        elif not files_are_identical(upstream_path, local_files[rel]):
            to_update.append(rel)

    for rel in sorted(local_files.keys()):
        if is_custom(rel):
            continue
        if rel not in upstream_files:
            to_delete.append(rel)

    # ========== 打印变更摘要 ==========
    print(f"  新增文件: {len(to_add)}")
    print(f"  更新文件: {len(to_update)}")
    print(f"  待删除文件: {len(to_delete)}")
    print()

    if to_add:
        print("--- 新增文件 ---")
        for f in to_add:
            print(f"  + {f}")
        print()

    if to_update:
        print("--- 更新文件 ---")
        for f in to_update:
            print(f"  ~ {f}")
        print()

    if to_delete:
        print("--- 待删除文件（需逐个确认）---")
        for f in to_delete:
            print(f"  - {f}")
        print()

    if not to_add and not to_update and not to_delete:
        print("✅ 没有需要同步的变更，已是最新版本。")
        sys.exit(0)

    if args.dry_run:
        print("(dry-run 模式，不执行实际操作)")
        sys.exit(0)

    if not confirm("是否开始同步?"):
        print("已取消。")
        sys.exit(0)

    # ========== 执行同步 ==========
    added = 0
    updated = 0
    deleted = 0
    skipped_delete = 0

    # 新增文件
    for rel in to_add:
        src = upstream_dir / rel
        dst = project_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  [新增] {rel}")
        added += 1

    # 更新文件
    for rel in to_update:
        src = upstream_dir / rel
        dst = project_dir / rel
        shutil.copy2(src, dst)
        print(f"  [更新] {rel}")
        updated += 1

    # 删除文件（逐个确认）
    for rel in to_delete:
        print(f"\n  本地文件在上游已不存在: {rel}")
        if confirm(f"  是否删除 {rel}?"):
            dst = project_dir / rel
            dst.unlink()
            print(f"  [已删除] {rel}")
            deleted += 1
            # 清理空目录
            parent = dst.parent
            while parent != project_dir and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        else:
            print(f"  [跳过] {rel}")
            skipped_delete += 1

    # ========== 完成报告 ==========
    print()
    print("=" * 60)
    print("  升级完成!")
    print("=" * 60)
    print(f"  新增: {added}")
    print(f"  更新: {updated}")
    print(f"  删除: {deleted}")
    if skipped_delete:
        print(f"  跳过删除: {skipped_delete}")
    print()
    print("  建议后续操作:")
    print("    1. git diff 查看变更详情")
    print("    2. pnpm install 更新依赖")
    print("    3. 测试功能是否正常")
    print("    4. git add && git commit 提交升级")
    print()

if __name__ == "__main__":
    main()
