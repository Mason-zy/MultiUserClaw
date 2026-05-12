#!/usr/bin/env python3
"""
Hermes Agent upgrade helper for Nanobot.

The tool compares an already-cloned upstream hermes-agent checkout with the
embedded ``hermes-agent/`` runtime directory. It is intentionally conservative:
the default mode is a dry-run report, and Nanobot overlay files are reported as
manual-merge items instead of being overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path

TARGET_DIR_NAME = "hermes-agent"
ROUTE_FILE = "gateway/platforms/api_server.py"

# Nanobot-owned overlay files. These either adapt Hermes to the platform
# contract or carry local seed data, so an upstream sync must not overwrite them.
PROTECTED_PATHS = {
    "AGENTS.md",
    "Dockerfile.bridge",
    "docker/entrypoint.sh",
    "gateway/platforms/nanobot_api_compat.py",
    "nanobot_hermes.py",
}
PROTECTED_PREFIXES = (
    "deploy_copy/",
)

SKIP_DIRS = {"node_modules", "dist", "dist-runtime", ".turbo", ".cache", ".pytest_cache"}
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "websocket"}


@dataclass(frozen=True, order=True)
class Route:
    method: str
    path: str


@dataclass
class RouteDiff:
    local_routes: list[Route] = field(default_factory=list)
    upstream_routes: list[Route] = field(default_factory=list)
    local_only: list[Route] = field(default_factory=list)
    upstream_only: list[Route] = field(default_factory=list)


@dataclass
class SyncPlan:
    to_add: list[str] = field(default_factory=list)
    to_update: list[str] = field(default_factory=list)
    to_delete: list[str] = field(default_factory=list)
    protected_add: list[str] = field(default_factory=list)
    protected_update: list[str] = field(default_factory=list)
    protected_delete: list[str] = field(default_factory=list)
    route_diff: RouteDiff = field(default_factory=RouteDiff)

    @property
    def has_file_changes(self) -> bool:
        return bool(self.to_add or self.to_update or self.to_delete)


def load_gitignore_patterns(project_dir: Path) -> list[str]:
    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        return []

    patterns = []
    for line in gitignore.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    parts = rel_path.split("/")
    for pattern in patterns:
        clean = pattern.rstrip("/")
        if "**" in clean:
            if fnmatch(rel_path, clean):
                return True
            simple = clean.replace("**/", "").replace("/**", "")
            if any(fnmatch(part, simple) for part in parts):
                return True
            continue

        if clean.startswith("/"):
            if fnmatch(rel_path, clean.lstrip("/")):
                return True
            continue

        if fnmatch(rel_path, clean) or any(fnmatch(part, clean) for part in parts):
            return True
    return False


def is_protected(rel_path: str) -> bool:
    return rel_path in PROTECTED_PATHS or any(rel_path.startswith(p) for p in PROTECTED_PREFIXES)


def collect_files(root: Path, gitignore_patterns: list[str] | None = None) -> dict[str, Path]:
    patterns = gitignore_patterns or []
    files: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git" and d not in SKIP_DIRS]
        for filename in filenames:
            full_path = Path(dirpath) / filename
            rel_path = str(full_path.relative_to(root)).replace("\\", "/")
            if is_ignored(rel_path, patterns):
                continue
            files[rel_path] = full_path
    return files


def files_are_identical(left: Path, right: Path) -> bool:
    try:
        return left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def _literal_after_open_paren(line: str) -> str | None:
    start = line.find("(")
    if start < 0:
        return None
    tail = line[start + 1 :].lstrip()
    if not tail or tail[0] not in {"'", '"'}:
        return None

    quote = tail[0]
    end = tail.find(quote, 1)
    if end < 0:
        return None
    return tail[1:end]


def extract_routes(api_server_path: Path) -> list[Route]:
    if not api_server_path.exists():
        return []

    routes = set()
    for raw_line in api_server_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        marker = ".router.add_"
        if marker in line:
            method_tail = line.split(marker, 1)[1]
            method = method_tail.split("(", 1)[0].lower()
            path = _literal_after_open_paren(line)
            if method in ROUTE_METHODS and path:
                routes.add(Route(method.upper(), path))
            continue

        if line.startswith("@") and ".route" not in line:
            before_paren = line.split("(", 1)[0]
            method = before_paren.rsplit(".", 1)[-1].lower()
            path = _literal_after_open_paren(line)
            if method in ROUTE_METHODS and path:
                routes.add(Route(method.upper(), path))

    return sorted(routes)


def analyze_route_diff(local_api_server: Path, upstream_api_server: Path) -> RouteDiff:
    local_routes = extract_routes(local_api_server)
    upstream_routes = extract_routes(upstream_api_server)
    local_set = set(local_routes)
    upstream_set = set(upstream_routes)
    return RouteDiff(
        local_routes=local_routes,
        upstream_routes=upstream_routes,
        local_only=sorted(local_set - upstream_set),
        upstream_only=sorted(upstream_set - local_set),
    )


def validate_upstream_hermes(upstream_dir: Path) -> None:
    if not upstream_dir.exists():
        raise ValueError(f"上游目录不存在: {upstream_dir}")
    if not (upstream_dir / ROUTE_FILE).exists():
        raise ValueError(f"{upstream_dir} 缺少 {ROUTE_FILE}，不像 hermes-agent 仓库")

    marker_files = [upstream_dir / "pyproject.toml", upstream_dir / "package.json"]
    if not any(path.exists() and "hermes" in path.read_text(encoding="utf-8").lower() for path in marker_files):
        raise ValueError(f"{upstream_dir} 缺少 Hermes 项目标识")


def check_git_clean(project_dir: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return True
    return result.stdout.strip() == ""


def analyze_sync(
    upstream_dir: Path,
    target_dir: Path,
    *,
    use_gitignore: bool = False,
) -> SyncPlan:
    validate_upstream_hermes(upstream_dir)
    if not target_dir.exists():
        raise ValueError(f"本地 Hermes 目录不存在: {target_dir}")

    gitignore_patterns = load_gitignore_patterns(target_dir) if use_gitignore else []
    upstream_files = collect_files(upstream_dir, gitignore_patterns)
    local_files = collect_files(target_dir, gitignore_patterns)

    plan = SyncPlan(
        route_diff=analyze_route_diff(target_dir / ROUTE_FILE, upstream_dir / ROUTE_FILE)
    )

    for rel_path, upstream_path in sorted(upstream_files.items()):
        if rel_path not in local_files:
            target = plan.protected_add if is_protected(rel_path) else plan.to_add
            target.append(rel_path)
        elif not files_are_identical(upstream_path, local_files[rel_path]):
            target = plan.protected_update if is_protected(rel_path) else plan.to_update
            target.append(rel_path)

    for rel_path in sorted(local_files):
        if rel_path not in upstream_files:
            target = plan.protected_delete if is_protected(rel_path) else plan.to_delete
            target.append(rel_path)

    return plan


def apply_sync(plan: SyncPlan, upstream_dir: Path, target_dir: Path, *, delete_missing: bool) -> dict[str, int]:
    counts = {"added": 0, "updated": 0, "deleted": 0}

    for rel_path in plan.to_add:
        src = upstream_dir / rel_path
        dst = target_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        counts["added"] += 1

    for rel_path in plan.to_update:
        src = upstream_dir / rel_path
        dst = target_dir / rel_path
        shutil.copy2(src, dst)
        counts["updated"] += 1

    if delete_missing:
        for rel_path in plan.to_delete:
            dst = target_dir / rel_path
            dst.unlink()
            counts["deleted"] += 1
            parent = dst.parent
            while parent != target_dir and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent

    return counts


def _route_label(route: Route) -> str:
    return f"{route.method} {route.path}"


def _print_section(title: str, items: list[str], marker: str) -> None:
    print(f"{title}: {len(items)}")
    for item in items:
        print(f"  {marker} {item}")
    print()


def print_plan(plan: SyncPlan, upstream_dir: Path, target_dir: Path) -> None:
    print("=" * 72)
    print("Hermes Agent 升级分析")
    print("=" * 72)
    print(f"上游仓库: {upstream_dir}")
    print(f"本地目录: {target_dir}")
    print()

    _print_section("新增文件", plan.to_add, "+")
    _print_section("更新文件", plan.to_update, "~")
    _print_section("本地多余文件", plan.to_delete, "-")

    if plan.protected_add or plan.protected_update or plan.protected_delete:
        print("受保护文件（不自动写入，需手工合并）:")
        for item in plan.protected_add:
            print(f"  + {item}")
        for item in plan.protected_update:
            print(f"  ~ {item}")
        for item in plan.protected_delete:
            print(f"  - {item}")
        print()

    route_diff = plan.route_diff
    print("Hermes API route 差异:")
    print(f"  本地 routes: {len(route_diff.local_routes)}")
    print(f"  上游 routes: {len(route_diff.upstream_routes)}")
    print(f"  上游新增 routes: {len(route_diff.upstream_only)}")
    for route in route_diff.upstream_only:
        print(f"    + {_route_label(route)}")
    print(f"  本地 overlay routes: {len(route_diff.local_only)}")
    for route in route_diff.local_only:
        print(f"    - {_route_label(route)}")
    print()

    if ROUTE_FILE in plan.protected_update:
        print(f"注意: {ROUTE_FILE} 已受保护。请手工合并上游 route，同时保留 Nanobot session/events overlay。")
        print()


def _plan_to_json(plan: SyncPlan) -> str:
    return json.dumps(asdict(plan), ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分析并同步上游 Hermes Agent 到本地 hermes-agent/")
    parser.add_argument("upstream_path", help="本地已 clone/pull 的上游 hermes-agent 仓库路径")
    parser.add_argument(
        "--target",
        default=str(Path(__file__).resolve().parent / TARGET_DIR_NAME),
        help="本地 Hermes 目标目录，默认 ./hermes-agent",
    )
    parser.add_argument("--apply", action="store_true", help="执行非保护文件的新增/更新")
    parser.add_argument(
        "--delete-missing",
        action="store_true",
        help="配合 --apply 删除上游已不存在的非保护文件；默认仅报告",
    )
    parser.add_argument(
        "--use-gitignore",
        action="store_true",
        help="使用目标目录 .gitignore 过滤文件；默认同步仓库文件清单",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 计划")
    args = parser.parse_args(argv)

    upstream_dir = Path(args.upstream_path).resolve()
    target_dir = Path(args.target).resolve()

    try:
        plan = analyze_sync(upstream_dir, target_dir, use_gitignore=args.use_gitignore)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(_plan_to_json(plan))
    else:
        print_plan(plan, upstream_dir, target_dir)

    if not args.apply:
        if not args.json:
            print("dry-run: 未写入文件。确认计划后使用 --apply 执行非保护文件同步。")
        return 0

    if not check_git_clean(Path(__file__).resolve().parent):
        print("错误: 当前仓库有未提交更改。请先提交或暂存，再执行 --apply。", file=sys.stderr)
        return 3

    counts = apply_sync(plan, upstream_dir, target_dir, delete_missing=args.delete_missing)
    print(
        "已同步: "
        f"新增 {counts['added']}，更新 {counts['updated']}，删除 {counts['deleted']}。"
    )
    if plan.protected_add or plan.protected_update or plan.protected_delete:
        print("仍有受保护文件未自动处理，请按上方清单手工合并。")
    if plan.to_delete and not args.delete_missing:
        print("上游缺失的非保护本地文件未删除；如确认需要删除，可重新运行 --apply --delete-missing。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
