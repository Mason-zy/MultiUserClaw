---
name: user-log-analyst
description: 基于 baime OCA 方法论分析多用户 hermes 容器日志：对话内容、业务主题、运行状态、效果评估。支持单用户或全量分析。
version: 1.0.0
---

# user-log-analyst — 用户日志分析 Skill

## 概述

从五路数据源采集用户 agent 运行数据，按 baime OCA 循环生成结构化分析报告：

```
Observe  → 采集日志/DB/资源数据
Classify → 业务主题 / 容器健康 / 响应质量 / 使用模式
Act      → 生成 markdown 分析报告 + 建议
```

## 数据源

| 数据源 | 采集内容 |
|--------|----------|
| `agent.log` | 对话轮次、模型、延迟、工具调用、token 消耗、错误 |
| `gateway.log` | 收发的消息内容、响应时长、平台 |
| `errors.log` | 错误与警告统计 |
| 平台 DB | 用户信息、容器状态、用量记录 |
| `docker stats` | CPU/内存资源占用 |

## 用法

```bash
# 分析所有用户
python3 analyze.py --all --days 7

# 分析指定用户
python3 analyze.py --user alice.liang@fjd.com --days 7

# 分析指定用户（按用户名）
python3 analyze.py --user Kit.Zhou --days 3

# 输出 JSON 格式
python3 analyze.py --all --format json
```

## 输出

Markdown 报告，包含四维分类：
1. **业务分析** — 用户问了什么、agent 做了什么、主题分布
2. **运行状态** — 容器 uptime、资源占用、cron 任务状态
3. **效果评估** — 响应速度、错误率、工具成功率、token 效率
4. **建议** — 基于分析结果的可操作建议
