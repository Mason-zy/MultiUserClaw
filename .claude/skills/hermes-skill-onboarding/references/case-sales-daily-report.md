# 案例：海外销售日报管道 → Alice 容器 skill

一次完整落地，作为本 skill 的实战参照。

## 输入
- 两个压缩包：`core`（scripts + docs + 样例产物）+ `addendum`（补 pyc + mapping + 原始 JSON）
- 目标：给 Alice（`alice.liang@fjd.com`，容器 `hermes-user-9c0d224f`）做成每天工作日 10:00 自动跑的 skill

## 分析阶段的关键发现
1. **源码损坏**：`sales_daily_pipeline.legacy.py` 中文 mojibake + `SyntaxError`（line 166 字符串未闭合）。原机器也没有干净 `.py`（addendum README 确认）。
2. **pyc 是唯一核心**：`sales_daily_pipeline.cpython-312.pyc`，magic `cb0d0d0a` = Python 3.12.0。
3. **版本不匹配**：容器自带 Python 3.13，跑 3.12 pyc 会 `bad magic number` → 用 uv 建 3.12 venv。
4. **凭证边界**：Odoo 三件套不在包里（用户补）；飞书凭据 `cli_aab48a50f2781bb7` 容器 `/opt/data/.env` 已注入（扫码 device flow 注入）。

## 落地结构
```
/opt/data/skills/sales-daily-report/   ← skill（hermes 自动加载）
  SKILL.md  scripts/  references/
/opt/data/sales-daily-report/          ← 工作目录（数据卷）
  venv/  mapping/  fixtures/  runs/  .env(600, Odoo 凭证)
/opt/data/scripts/cron_publish.sh      ← cron 脚本区
```

## 验证
- **offline**：用 fixtures 的 2026-06-25 原始 JSON 跑 pyc，产出指标与基线一致（39 人 / 26 提交 / 18 群组），中文正常。
- **online**：注入 Odoo 凭证跑，结构指标稳定，业绩金额小幅变化（10:00 vs 17:00 拉取的时效性差异，正常）。

## 推送
- **卡片**：`push_card.py` 复用 `feishu_publish.build_daily_cards`，发送层直接 HTTP（用 `.env` 的 app 凭据换 token），**不依赖 lark-cli**。
- **文本**（meta-skill 默认）：同样直接 HTTP，`msg_type=text`，最先验证渠道联通用这个。
- **目标**：`channel_directory.json` 里 feishu 的 `dm` chat（bot 和用户的 P2P），bot 天然在内，**不需拉群**。

## cron
```bash
hermes cron create "0 10 * * 1-5" --name sales-daily-report \
  --no-agent --script cron_publish.sh --workdir /opt/data/sales-daily-report
```
- ticker 实测触发成功（`hermes cron run <id>` + 等 60s，`cron/output/` 有执行记录，卡片重发成功）。
- `hermes cron status` 报 "Gateway not running" 是**误报**（PID 1 gateway 在跑，`run.py:16988` 启动了 cron-ticker）。

## 速查命令
```bash
C=hermes-user-9c0d224f
# 生成（自动读工作目录 .env 的凭证）
docker exec -u hermes "$C" bash /opt/data/skills/sales-daily-report/scripts/run_daily_report.sh
# 推卡片
docker exec -u hermes "$C" /opt/data/sales-daily-report/venv/bin/python \
  /opt/data/skills/sales-daily-report/scripts/push_card.py <chat_id> <date> summary
# cron 列表
docker exec -u hermes "$C" /opt/hermes/.venv/bin/hermes cron list
```
