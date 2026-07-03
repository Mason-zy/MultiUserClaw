---
id: TASK-4
title: vision 模型从 glm-5.1 切 gpt-5.4（glm 系列不支持图片识别）
status: 'Basic: Done'
assignee: []
created_date: '2026-07-03'
updated_date: '2026-07-03'
labels:
  - 'kind:basic'
dependencies: []
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
实测 glm-5.1/glm-5.2 均不支持 vision：1x1 像素 PNG 送进去，glm-5.1 编造"鸟站在树枝上"，glm-5.2 编造"水滴挂在叶尖"——完全忽略图片，凭文字 prompt 白日造梦。gpt-5.4 如实描述"solid green square"。

根因：TASK-1 注入 auxiliary.vision 时 model 写死了 glm-5.1，但智谱 GLM 系列实际无 vision 能力（API 不报错但直接丢弃图片）。

修复：
1. `manager.py:241` 改 vision model → `openai/gpt-5.4`（新容器生效）
2. 3 个运行中容器 `sed` config.yaml（下条消息立即生效）
3. 可选：model 改为 config.py 可配置项（env `PLATFORM_DEDICATED_HERMES_DEFAULT_VISION_MODEL` 可调）

DoD：任选一容器发图片测试，回复不再胡说八道。
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
### Step 1 — manager.py 改 vision model 默认值

`manager.py:241` `"model": "openai/glm-5.1"` → `"openai/gpt-5.4"`

### Step 2 — config.py 加可配置项（可选但推荐）

`config.py` 加 `dedicated_hermes_default_vision_model: str = "openai/gpt-5.4"`，manager.py 读 `settings.dedicated_hermes_default_vision_model`。

### Step 3 — 存量容器热修复

3 个容器的 `/opt/data/config.yaml`：
```bash
sed -i 's|model: openai/glm-5.1|model: openai/gpt-5.4|' /opt/data/config.yaml
```
改完下条消息即生效（agent `_create_agent` 每 run 读盘）。

### Step 4 — 验证

找 alice 或其他容器发一张图片，检查回复是否准确识别图片内容。
<!-- SECTION:PLAN:END -->
