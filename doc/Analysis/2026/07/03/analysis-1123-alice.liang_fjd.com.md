# Hermes 用户日志深度分析报告

**生成时间**: 2026-07-03 11:23 (Asia/Shanghai)
**分析范围**: 最近 7 天
**用户数**: 1
**方法**: baime OCA（深度根因分析 + 业务级洞察）

---

## 1. 总体发现

### 🔴 P0 — 立即处理（1 项）

- **cron `sales-daily-report` 最近一次运行失败** — 若不修复，下一次触发 2026-07-06T10:00:00+08:00 将继续失败

### 🟡 P1 — 本周处理（3 项）

- **cron `sales-daily-report` 最近 output 文件包含错误** — cron 执行中途出错，部分产物可能不完整
- **vision 图片识别未配置 provider（27 次）** — 用户发图片消息时，图片内容分析会失败；文本回复仍正常
- **LLM 额度/限流错误（20 次）** — LLM 调用被拒绝，agent 无法回复或回复延迟（依赖重试）

### 🟢 P2 — 持续改进（5 项）

- **辅助模型（auxiliary）不可用（60 次）**
- **大量 LLM 请求超时（93 次）**
- **连接错误（65 次）**
- **agent.log API 调用数(268) 与 usage_records(214) 差距 54 条**
- **containers.last_active_at 滞后于实际飞书消息活跃时间**

---

## 2. 业务维度总览

### 用户画像

销售运营

主题分布: 其他(14), 销售日报管理(14), 配置变更(1), 团队协作/管理(1)

### 核心工作流

分为 5 个阶段: 配置实现, 正式发布, 需求变更, 监控反馈, 测试验证

用户遵循「需求变更 → 配置实现 → 测试验证 → 正式发布」的标准工作流
最近活动: 需求变更/监控反馈/测试验证

### 使用密度

7 天内有 6 天有对话, 日均 4 条消息, 日均 38 次 LLM 调用, 平均每会话 30 次 LLM 调用

最长会话: 685 分钟
趋势: ↓ 下降

### 效率分析

总 token 7,575,953, 平均每轮对话 140,295 tokens, 工具调用成功率 98.0%

占日限额比例: 37.9%
缓存命中率: 70.5%
工具调用 vs LLM 调用比: 0.90

### 平台依赖度

依赖度评分: 8/10 (高度依赖（平台已成为核心业务工具，故障直接影响业务）)
高频使用; 1 个定时任务(sales-daily-report); 使用 13 种工具（重度定制）; 1 项 P0 问题导致业务中断

活跃 6/7 天
基础设施依赖: cron 定时任务
工具使用广度: 13 种 (browser_navigate, cronjob, execute_code, memory, patch, read_file, search_files, session_search, skill_manage, skill_view)

**建议**: 建议纳入核心监控，cron 任务加告警

### Cron 定时任务业务影响

sales-daily-report 定时推送（0 10 * * 1-5）失败
影响面: 18 个销售区域的日报未推送
数据生成阶段: ✅ 完成
推送阶段: ❌ 失败（路径错误）

该任务是 alice 的核心业务流程——每个工作日 10:00 向 18 个区域群推送销售日报卡片
失效后各区域负责人无法在飞书收到当日业绩数据，管理层缺少决策依据
根因: push_card.py 的 positional arg 被 DATE 覆盖导致路径误读为 run-summary 而非 run-YYYY-MM-DD

**建议**: 已修复并手动补推。建议在 cron 脚本末尾加健康检查——如果 exit code≠0 则通知管理员。也建议 cron output 文件加一个 sentinel 标记'推送已完成'以便巡检。

### 对话协作模式

私聊 30 条 / 群聊 0 条 (100% 私聊)
@all 消息 3 次

用户主要用私聊与 agent 交互（测试、验证、指令），群聊用于团队协调
注意: 3 次 @all 消息可能触发 agent 不必要的群回复

**建议**: 在群聊中已配置 agent 不响应 @all

---

## 3. 逐用户技术详情

## alice.liang@fjd.com

### 账号与容器

| 项目 | 值 |
|------|-----|
| 容器名 | `hermes-user-9c0d224f` |
| CPU | 0.08% |
| 内存 | 427.1MiB / 2GiB |
| 7 天 token | 7,575,953 |
| DB 用量记录 | 214 条 |

### 活跃概览

| 指标 | 值 |
|------|-----|
| 飞书收消息 | 30 条 |
| 飞书发回复 | 30 条 |
| Agent API 调用 | 268 次 |
| 平均响应时间 | 342.4s |
| 最长响应时间 | 1543.4s |

### 工具使用

| 工具 | 次数 |
|------|------|
| terminal | 55 |
| execute_code | 53 |
| read_file | 31 |
| skill_view | 25 |
| search_files | 21 |
| skill_manage | 21 |
| patch | 12 |
| todo | 7 |
| memory | 6 |
| skills_list | 3 |

### 最近对话

- `2026-07-02 10:41:10` [Mentioned: @all]  @all 组长看下各自组员的填报情况，有没有问题。没问题自己再提醒未填写的同事，后续基本动作不能达标是直接影响绩效工资和留
- `2026-07-02 11:31:51` 群聊@所有人时，不要响应，判断也不要发
- `2026-07-02 14:04:28` 销售日报推送做三个变动：1.拉取人员以该表进行更新https://fjdynamics.feishu.cn/sheets/Rj4nsG37ghT3v7t01Z4
- `2026-07-02 14:15:08` 按修改后的拉取7.1的数据，私发我验证，不要在群里推送
- `2026-07-02 14:18:23` 具体日报推送给我
- `2026-07-02 14:20:03` 按正式的格式，18个区域都发我
- `2026-07-02 15:16:57` 没问题，明天开始推送
- `2026-07-02 22:49:14` ' reply_to_id=None reply_to_text='
- `2026-07-03 10:01:18` 今天的日报推送正常么' reply_to_id=None reply_to_text='
- `2026-07-03 10:32:05` [Mentioned: @all]  @all 后台模型有问题，在排查中，今日日报推送待排查完成推送，请知悉 [Image]' reply_to_id=None reply_to_text='
- `2026-07-03 10:35:47` 不要在群里回复@所有人的信息' reply_to_id=None reply_to_text='
- `2026-07-03 10:59:29` 团队整体日报补推一份到组长群' reply_to_id=None reply_to_text='

### 📊 业务洞察

**用户画像**: 销售运营

主题分布: 其他(14), 销售日报管理(14), 配置变更(1), 团队协作/管理(1)

**核心工作流**: 分为 5 个阶段: 配置实现, 正式发布, 需求变更, 监控反馈, 测试验证

用户遵循「需求变更 → 配置实现 → 测试验证 → 正式发布」的标准工作流
最近活动: 需求变更/监控反馈/测试验证

**使用密度**: 7 天内有 6 天有对话, 日均 4 条消息, 日均 38 次 LLM 调用, 平均每会话 30 次 LLM 调用

最长会话: 685 分钟
趋势: ↓ 下降

**效率分析**: 总 token 7,575,953, 平均每轮对话 140,295 tokens, 工具调用成功率 98.0%

占日限额比例: 37.9%
缓存命中率: 70.5%
工具调用 vs LLM 调用比: 0.90

**平台依赖度**: 依赖度评分: 8/10 (高度依赖（平台已成为核心业务工具，故障直接影响业务）)
高频使用; 1 个定时任务(sales-daily-report); 使用 13 种工具（重度定制）; 1 项 P0 问题导致业务中断

活跃 6/7 天
基础设施依赖: cron 定时任务
工具使用广度: 13 种 (browser_navigate, cronjob, execute_code, memory, patch, read_file, search_files, session_search, skill_manage, skill_view)

→ 建议纳入核心监控，cron 任务加告警

**Cron 定时任务业务影响**: sales-daily-report 定时推送（0 10 * * 1-5）失败
影响面: 18 个销售区域的日报未推送
数据生成阶段: ✅ 完成
推送阶段: ❌ 失败（路径错误）

该任务是 alice 的核心业务流程——每个工作日 10:00 向 18 个区域群推送销售日报卡片
失效后各区域负责人无法在飞书收到当日业绩数据，管理层缺少决策依据
根因: push_card.py 的 positional arg 被 DATE 覆盖导致路径误读为 run-summary 而非 run-YYYY-MM-DD

→ 已修复并手动补推。建议在 cron 脚本末尾加健康检查——如果 exit code≠0 则通知管理员。也建议 cron output 文件加一个 sentinel 标记'推送已完成'以便巡检。

**对话协作模式**: 私聊 30 条 / 群聊 0 条 (100% 私聊)
@all 消息 3 次

用户主要用私聊与 agent 交互（测试、验证、指令），群聊用于团队协调
注意: 3 次 @all 消息可能触发 agent 不必要的群回复

→ 在群聊中已配置 agent 不响应 @all


### 🔍 需要关注（技术层面）

#### P0 — cron `sales-daily-report` 最近一次运行失败

**证据**
```
last_run_at: 2026-07-03T10:00:52.204303+08:00
last_status: error
next_run_at: 2026-07-06T10:00:00+08:00
根因: 脚本尝试读取不存在的文件: `/opt/data/sales-daily-report/runs/run-summary/team_message_summary.json`
原始错误(截断): Script exited with code 1
stderr:
Traceback (most recent call last):
  File "/opt/data/skills/sales-daily-report/scripts/push_card.py", line 329, in <module>
    main()
  File "/opt/data/skills/sales-daily-report/scripts/push_card.py", line 255, in main
    team = load_team_message(run / f"team_message_{args.date}.json")
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/data/skills/sales-daily-report/scripts/feishu_publish.py", line 163, in load_team_message
    p
```

**影响**：若不修复，下一次触发 2026-07-06T10:00:00+08:00 将继续失败

**修复方向**：定位被破坏的路径/参数: 脚本尝试读取不存在的文件: `/opt/data/sales-daily-report/runs/run-summary/team_message_summary.json`。修复后手动 dry-run 验证: 在容器内 `hermes-user-9c0d224f` 执行对应的 cron 脚本。

#### P1 — cron `sales-daily-report` 最近 output 文件包含错误

**证据**
```
output 文件: 2026-07-03_10-00-52.md
# Cron Job: sales-daily-report

**Job ID:** e8466e34f7ad
**Run Time:** 2026-07-03 10:00:52
**Mode:** no_agent (script)
**Status:** script failed

Script exited with code 1
stderr:
Traceback (most recent call last):
  File "/opt/data/skills/sales-daily-report/scripts/push_card.py", line 329, in <module>
    main()
  File "/opt/data/skills/sales-daily-report/scripts/push_card.py", line 255, in main
    team = load_team_message(run / f"team_message_{args.date}.json")
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/data/skills/sales-daily-report/scripts/feishu_publish.py", line 163, in load_team_message
    payload = json.loads(path.read_text(encoding="utf-8"))
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "
```

**影响**：cron 执行中途出错，部分产物可能不完整

#### P1 — vision 图片识别未配置 provider（27 次）

**证据**
```
最近一条: RuntimeError: No LLM provider configured for task=vision provider=auto. Run: hermes setup
主 LLM 走 platform-gateway 正常，但 vision task 走 provider=auto 时找不到可用 provider
```

**影响**：用户发图片消息时，图片内容分析会失败；文本回复仍正常

**修复方向**：在 config.yaml 或 .env 中为 vision task 显式配置 provider（如 platform-gateway），避免 fallback 到 auto → OpenRouter/Nous

#### P2 — 辅助模型（auxiliary）不可用（60 次）

**证据**
```
最近一条: 2026-07-03 10:59:30,047 WARNING agent.auxiliary_client: Auxiliary Nous client unavailable: no Nous authentication found (run: hermes auth).
```

**影响**：辅助任务（如 Nous/OpenRouter 补强）不可用，但不影响主 LLM 对话

**修复方向**：如不需要辅助模型，在 config.yaml 中关闭 auxiliary；需要则配置可用的 provider 凭证

#### P1 — LLM 额度/限流错误（20 次）

**证据**
```
最近一条: 2026-07-03 10:27:02,195 ERROR [20260703_100118_cd0b300f] agent.conversation_loop: API call failed after 3 retries. HTTP 502: Error code: 502 - {'detail': 'LLM provider error: litellm.RateLimitError: RateLimitError: OpenAIException - litellm.RateLimitError: AnthropicException - b\'{"type":"error","er
关键错误码: 1113 余额不足 / rate_limit_error / usage limit
```

**影响**：LLM 调用被拒绝，agent 无法回复或回复延迟（依赖重试）

**修复方向**：检查 fjbigmodel 余额或切换模型。已紧急切换到 deepseek-v4-pro-anthropic 恢复服务。长期建议配多个有额度的 provider fallback。

#### P2 — 大量 LLM 请求超时（93 次）

**证据**
```
Request timed out 出现 93 次
```

**影响**：部分 API 调用可能卡住 agent 直到超时重试，增加响应延迟

**修复方向**：检查网络到 fjbigmodel.fjdac.cn 的延迟和丢包；考虑设更短的 LLM 超时时间加快失败回退

#### P2 — 连接错误（65 次）

**证据**
```
Connection error 出现 65 次
```

**影响**：可能与 gateway 重启或网络波动同步；模型切换到 deepseek 后需观察是否减少

#### P2 — agent.log API 调用数(268) 与 usage_records(214) 差距 54 条

**证据**
```
agent.log 侧: 268 次 API 调用
usage_records: 214 条记录
差距 54 条 = 失败/重试/辅助调用/计量落库口径不同
```

**影响**：平台用量统计低估了实际 LLM 调用量；计量和计费可能不精确

#### P2 — containers.last_active_at 滞后于实际飞书消息活跃时间

**证据**
```
DB last_active_at: 2026-07-03 02:10:40.462993
gateway.log 最新飞书消息: 2026-07-03 10:59:29
差距: 8.8 小时
```

**影响**：依赖 DB last_active_at 的监控/告警会误报用户不活跃

**修复方向**：排查网关代理层是否在代理用户容器请求时更新 containers.last_active_at

---

## 复查命令

### alice.liang@fjd.com

```bash
# 容器健康
sudo docker exec hermes-user-9c0d224f curl -s http://127.0.0.1:18080/health

# 最近网关消息
sudo docker exec hermes-user-9c0d224f grep -E "inbound message|response ready" /opt/data/logs/gateway.log | tail -20

# 最近 agent 对话
sudo docker exec hermes-user-9c0d224f grep -E "conversation turn|API call|Turn ended" /opt/data/logs/agent.log | tail -20

# cron 状态
sudo docker exec hermes-user-9c0d224f grep -E "last_status|last_error|next_run" /opt/data/cron/jobs.json

# 错误
sudo docker exec hermes-user-9c0d224f tail -30 /opt/data/logs/errors.log
```


---
*报告由 user-log-analyst v2 (baime OCA) 自动生成*
