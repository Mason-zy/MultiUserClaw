#!/usr/bin/env python3
"""删除在中国服务器环境下用不到的 OpenClaw skills"""

import os
import shutil

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes-agent", "skills")

# 删除在中国服务器环境下用不到的 Hermes Agent skills
SKILLS_TO_DELETE = [
    # === Apple 生态系统（需要 macOS 桌面环境）===
    "apple",           # 整个 Apple 分类（apple-notes, apple-reminders, findmy, imessage）

    # === 游戏（与医学AI平台无关）===
    "gaming",          # 整个 Gaming 分类（minecraft-modpack-server, pokemon-player）

    # === 笔记工具（需要桌面端）===
    "note-taking",     # 整个 note-taking 分类（obsidian）

    # === 社交媒体（与医学AI平台无关）===
    "social-media",    # 整个 social-media 分类（xitter）
]


def main():
    # 统计当前 skills
    all_skills = [
        d for d in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, d)) and not d.startswith(".")
    ]
    print(f"当前共有 {len(all_skills)} 个 skills")

    # 确认要删除的
    existing = [s for s in SKILLS_TO_DELETE if s in all_skills]
    missing = [s for s in SKILLS_TO_DELETE if s not in all_skills]
    if missing:
        print(f"以下 {len(missing)} 个 skill 未找到，跳过: {', '.join(missing)}")

    print(f"即将删除 {len(existing)} 个 skills: {', '.join(existing)}")
    print()

    # 执行删除
    deleted = 0
    for skill in existing:
        path = os.path.join(SKILLS_DIR, skill)
        try:
            shutil.rmtree(path)
            print(f"  ✓ 已删除 {skill}")
            deleted += 1
        except Exception as e:
            print(f"  ✗ 删除 {skill} 失败: {e}")

    # 统计剩余
    remaining = [
        d for d in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, d)) and not d.startswith(".")
    ]
    print()
    print(f"删除完成: 成功删除 {deleted} 个, 剩余 {len(remaining)} 个 skills")


if __name__ == "__main__":
    main()
