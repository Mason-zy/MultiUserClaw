# Alice 使用日志分析

分析日期：2026-07-03  
时区：Asia/Shanghai  
对象：Alice / `alice.liang@fjd.com` / `alice.liang@fjdynamics.com`  
用户 ID：`9c0d224f-d029-4d61-890d-ac74a2d69e72`  
容器：`hermes-user-9c0d224f`

## 1. 结论

Alice 当前平台账号、Hermes 容器、飞书 websocket、历史会话和主聊天窗口数据都在新服务器上存在且可读。

已验证：

- 平台用户状态：`is_active=true`，`runtime_mode=dedicated`。
- 容器状态：`hermes-user-9c0d224f` 运行中，健康检查返回 `{"status":"ok","platform":"hermes-agent","version":"0.17.0"}`。
- 容器内部模型配置：`provider=platform-gateway`，`default=openai/glm-5.1`，`base_url=http://gateway:8080/llm/v1`。
- 飞书连接：迁移后日志显示 `[Feishu] Connected in websocket mode (feishu)` 和 `✓ feishu connected`。
- 历史会话：`/opt/data/sessions/` 下保留 2026-06-26 至 2026-07-02 的会话文件；`sessions.json` 保留飞书 DM 和 group 路由索引。
- 最近一次用户消息处理：2026-07-02 22:49 收到图片和文本消息，2026-07-02 22:57 返回响应。

需要关注：

- `sales-daily-report` cron 在 2026-07-03 10:00:52 最近一次运行结果为 `error`，原因是脚本尝试读取不存在的 `/opt/data/sales-daily-report/runs/run-summary/team_message_summary.json`。
- 图片识别链路在 2026-07-02 22:52 和 22:57 出现 `No LLM provider configured for task=vision provider=auto`，但主 LLM 仍走 `platform-gateway` 并给出了文本响应。
- 日志中多次出现 `Request timed out`、`Connection error`、辅助模型不可用、工具执行失败。这些不是容器不可用，而是具体任务执行过程中的外部 API、辅助模型或脚本问题。

## 2. 数据来源

平台数据库：

```text
openclaw-postgres / nanobot_platform
users
containers
usage_records
audit_logs
```

Hermes 容器日志：

```text
hermes-user-9c0d224f:/opt/data/logs/gateway.log
hermes-user-9c0d224f:/opt/data/logs/agent.log
hermes-user-9c0d224f:/opt/data/logs/errors.log
```

Hermes 状态文件：

```text
hermes-user-9c0d224f:/opt/data/config.yaml
hermes-user-9c0d224f:/opt/data/sessions/
hermes-user-9c0d224f:/opt/data/sessions/sessions.json
hermes-user-9c0d224f:/opt/data/cron/jobs.json
hermes-user-9c0d224f:/opt/data/cron/output/
hermes-user-9c0d224f:/opt/data/sales-daily-report/runs/
```

## 3. 平台账号和容器状态

数据库核实结果：

```text
id                   9c0d224f-d029-4d61-890d-ac74a2d69e72
username             alice.liang@fjd.com
email                alice.liang@fjdynamics.com
role                 user
quota_tier           free
runtime_mode         dedicated
is_active            true
created_at           2026-06-26 08:17:53.9117
container_record_id  bd5195b6-07f3-497c-94fd-2fff4f93f877
docker_id            d4a39382a7cb7a052e105edb3b1137deffaf7c02d116f52af087e5099289c4f4
status               running
internal_host        172.19.0.7
internal_port        18080
container_created_at 2026-07-02 09:00:23.66339
last_active_at       2026-07-02 14:50:03.116228
```

容器健康检查：

```json
{"status": "ok", "platform": "hermes-agent", "version": "0.17.0"}
```

模型配置：

```yaml
model:
  default: openai/glm-5.1
  provider: platform-gateway
  base_url: http://gateway:8080/llm/v1
```

## 4. 平台 usage / audit 统计

### 4.1 usage_records

Alice 在平台 usage 表中共有 199 条记录，全部模型为：

```text
model=openai/glm-5.1
provider_id=openai
upstream_model=openai/glm-5.1
```

累计 token：

```text
input_tokens   7,013,450
output_tokens     63,929
total_tokens   7,077,379
```

按北京时间聚合：

| 日期 | 调用数 | input_tokens | output_tokens | total_tokens | 首次 | 最后 |
|---|---:|---:|---:|---:|---|---|
| 2026-06-26 | 36 | 1,267,441 | 8,936 | 1,276,377 | 17:07:03 | 18:54:53 |
| 2026-06-29 | 63 | 2,095,451 | 14,233 | 2,109,684 | 09:58:49 | 15:25:04 |
| 2026-06-30 | 28 | 529,323 | 10,981 | 540,304 | 13:45:03 | 16:54:12 |
| 2026-07-01 | 26 | 733,293 | 9,699 | 742,992 | 10:09:53 | 13:58:35 |
| 2026-07-02 | 46 | 2,387,942 | 20,080 | 2,408,022 | 10:41:18 | 22:57:03 |

### 4.2 audit_logs

Alice 在 audit 表中共有 219 条记录：

| action | 条数 | 首次北京时间 | 最后北京时间 |
|---|---:|---|---|
| `llm_call` | 213 | 2026-06-26 17:07:03 | 2026-07-02 22:57:17 |
| `login` | 6 | 2026-06-26 17:57:00 | 2026-07-02 17:15:15 |

说明：`audit_logs.llm_call=213` 多于 `usage_records=199`，表示部分 LLM 调用有审计记录但没有成功落 usage，常见于失败、重试或未完整计量的调用。

## 5. Hermes gateway 使用日志

`gateway.log` 显示飞书消息、响应、session expiry、重启和 websocket 状态。

### 5.1 飞书连接

迁移后关键日志：

```text
2026-07-02 17:00:36 Starting Hermes Gateway
2026-07-02 17:00:36 [Feishu] Connected in websocket mode (feishu)
2026-07-02 17:00:36 ✓ feishu connected
2026-07-02 17:00:37 Gateway housekeeping started
```

2026-07-02 16:56 容器内 gateway 收到 SIGTERM 后正常退出，17:00 重新启动并恢复飞书连接：

```text
2026-07-02 16:56:08 Received SIGTERM — initiating shutdown
2026-07-02 16:56:09 [Feishu] Disconnected
2026-07-02 17:00:36 Starting Hermes Gateway
2026-07-02 17:00:36 ✓ feishu connected
```

### 5.2 消息和响应统计

从 `gateway.log` 聚合：

```text
DM inbound:
2026-06-26  4
2026-06-29  8
2026-06-30  2
2026-07-01  4
2026-07-02  8
2026-07-03  2

Group inbound:
2026-07-01  1
2026-07-02  1
```

`response ready` 聚合：

```text
2026-06-26  4
2026-06-29  8
2026-06-30  2
2026-07-01  4
2026-07-02  8
```

响应统计：

```text
responses       26
avg_time        304.3s
max_time        1467.7s
avg_api_calls   6.1
avg_chars       328.0
```

最长响应：

```text
2026-06-30 16:31:27 response ready ... time=1467.7s api_calls=24 response=48 chars
```

### 5.3 最近飞书交互

2026-07-02 22:49 收到图片：

```text
2026-07-02 22:49:11 Received raw message type=image
2026-07-02 22:49:12 Inbound dm message received ... type=photo ... media=1
2026-07-02 22:49:14 inbound message ... msg=''
```

随后收到文字：

```text
2026-07-02 22:49:23 Received raw message type=text
2026-07-02 22:49:23 text='检索这个照片上的公司信息'
```

最终返回：

```text
2026-07-02 22:57:17 response ready ... time=483.4s api_calls=2 response=101 chars
2026-07-02 22:57:17 Sending response (101 chars)
```

## 6. Hermes agent 使用日志

`agent.log` 显示 LLM provider、API 调用、工具执行和异常。

### 6.1 LLM 调用

日志侧聚合到的 `openai/glm-5.1 provider=custom` 调用：

```text
2026-06-26  50
2026-06-29  79
2026-06-30  40
2026-07-01  28
2026-07-02  55
```

日志侧累计：

```text
calls          252
input_tokens   9,004,683
output_tokens     62,296
total_tokens   9,066,979
avg_latency       39.3s
max_latency      270.1s
```

最长单次 LLM 调用：

```text
2026-07-02 22:57:03 API call #1: model=openai/glm-5.1 provider=custom in=85235 out=64 total=85299 latency=270.1s
```

说明：日志侧调用数 252 多于平台 usage 表 199，原因通常是 agent 内部多轮调用、失败重试、辅助调用或计量落库口径不同。

### 6.2 Provider 是否正确

日志中多次出现：

```text
OpenAI client created ... provider=custom base_url=http://gateway:8080/llm/v1 model=openai/glm-5.1
```

这里的 `provider=custom` 是 Hermes 内部 provider 客户端名；对应 `config.yaml` 的 `platform-gateway`，实际走平台 gateway 的 `/llm/v1`。

结论：Alice 当前主 LLM provider 路由正确，不是 401 或 OpenRouter 路由问题。

### 6.3 错误和警告聚合

从 `agent.log` 和 `errors.log` 聚合：

| 模式 | 次数 |
|---|---:|
| `Request timed out` | 93 |
| `API call failed` | 54 |
| `Tool .* returned error` | 46 |
| `Connection error` | 29 |
| `No LLM provider configured for task=vision` | 23 |
| `Unrepairable tool_call arguments` | 22 |
| `Auxiliary auto-detect: no provider available` | 16 |

这些记录说明 Alice 历史任务里存在外部 API 慢、连接失败、工具脚本报错、视觉辅助模型配置缺失等问题，但主服务没有停止。

## 7. 历史会话和主窗口

`/opt/data/sessions/` 中保留的会话文件覆盖 2026-06-26 到 2026-07-02。主要文件包括：

```text
session_20260626_170652_d2bdd743.json
session_20260629_101218_112b4b70.json
session_20260630_160700_998ff9f2.json
session_20260701_100951_b4ca2864.json
session_20260701_135750_94814f0b.json
session_20260702_104111_495dd549.json
session_20260702_113151_5809c05f.json
session_20260702_141236_1a88a9.json
session_20260702_151707_c4af64.json
```

`sessions.json` 是 gateway routing index，当前保留 3 条飞书路由：

```text
agent:main:feishu:dm:<dm_chat_id> -> 20260702_113151_5809c05f
agent:main:feishu:group:<group_chat_id>:<sender_1> -> 20260701_135750_94814f0b
agent:main:feishu:group:<group_chat_id>:<sender_2> -> 20260702_104111_495dd549
```

其中 DM 路由更新时间：

```text
created_at 2026-07-02T11:31:51
updated_at 2026-07-02T22:57:17
```

结论：主窗口和飞书会话索引没有丢失。

## 8. Cron 和销售日报任务

Alice 容器中存在 cron 任务：

```text
id          e8466e34f7ad
name        sales-daily-report
schedule    0 10 * * 1-5
enabled     true
state       scheduled
completed   6
next_run    2026-07-06T10:00:00+08:00
last_run    2026-07-03T10:00:52+08:00
last_status error
```

历史 cron output 文件：

```text
2026-06-26_18-01-58.md
2026-06-29_10-00-41.md
2026-06-30_10-01-12.md
2026-07-01_10-01-37.md
2026-07-02_10-00-59.md
2026-07-03_10-00-52.md
```

2026-07-03 10:00 的任务生成了 2026-07-02 数据目录：

```text
/opt/data/sales-daily-report/runs/run-2026-07-02/
daily_report_2026-07-02_all_visible.json
group_analysis_2026-07-02.md
group_messages_2026-07-02.json
normalized_sales_daily_2026-07-02.csv
odoo_c01_2026_07.json
odoo_c02_2026_07.json
summary_2026-07-02.json
team_analysis_2026-07-02.md
team_message_2026-07-02.json
```

但最终推送失败：

```text
FileNotFoundError:
/opt/data/sales-daily-report/runs/run-summary/team_message_summary.json
```

判断：

- 数据生成阶段已完成。
- 失败发生在 `push_card.py` 推送阶段。
- 脚本当前错误地去 `run-summary` 找 `team_message_summary.json`，而实际产物在 `run-2026-07-02/team_message_2026-07-02.json`。

## 9. 风险点

1. `sales-daily-report` 最近一次 cron 是 error。若不修，2026-07-06 10:00 下一次工作日定时任务可能继续失败。
2. vision 图片任务配置不完整。普通文本 LLM 正常，但图片二次分析会报 `No LLM provider configured for task=vision provider=auto`。
3. 平台 `containers.last_active_at` 停在 2026-07-02 14:50，晚于这个时间的飞书消息仍在 Hermes 内部日志中处理。这说明平台容器活跃时间不一定反映飞书消息活跃度，排查 Alice 必须继续以 `/opt/data/logs/` 为准。
4. `errors.log` 历史中有较多 `Request timed out` 和 `Connection error`，需要区分外部服务波动和系统故障。

## 10. 建议动作

优先级 P0：

- 修复 `sales-daily-report` 的推送路径逻辑：`push_card.py` 不应从 `run-summary/team_message_summary.json` 读取当前日报卡片，应按当前报告日期读取 `run-YYYY-MM-DD/team_message_YYYY-MM-DD.json`，或在生成阶段同步创建 `run-summary` 所需文件。
- 修复后手动 dry run 2026-07-02 数据，确认能私发或正式推送。

优先级 P1：

- 为 vision task 明确配置 provider，避免图片消息走 `provider=auto` 时尝试 OpenRouter / Nous 后失败。
- 对 Alice 的 cron 增加一次迁移后巡检：每天 10:05 检查 `jobs.json.last_status` 和 `/opt/data/cron/output/`。

优先级 P2：

- 将 `containers.last_active_at` 与 Hermes 飞书消息活跃度脱钩的问题记录为平台观测盲点；后续可在 gateway 代理层收到用户容器事件时更新。

## 11. 复查命令

账号和容器：

```bash
sudo docker exec openclaw-postgres psql -U nanobot -d nanobot_platform -x -c "
SELECT u.id,u.username,u.email,u.is_active,c.status,c.internal_host,c.internal_port,c.last_active_at
FROM users u
LEFT JOIN containers c ON c.user_id=u.id
WHERE u.id='9c0d224f-d029-4d61-890d-ac74a2d69e72';
"
```

健康检查：

```bash
sudo docker exec hermes-user-9c0d224f curl -sS http://127.0.0.1:18080/health
```

业务日志：

```bash
sudo docker exec hermes-user-9c0d224f tail -n 200 /opt/data/logs/gateway.log
sudo docker exec hermes-user-9c0d224f tail -n 200 /opt/data/logs/agent.log
sudo docker exec hermes-user-9c0d224f tail -n 100 /opt/data/logs/errors.log
```

cron 状态：

```bash
sudo docker exec -u hermes hermes-user-9c0d224f /opt/hermes/.venv/bin/hermes cron list
sudo docker exec hermes-user-9c0d224f cat /opt/data/cron/jobs.json
```
