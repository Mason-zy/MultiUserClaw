---
name: multiuserclaw-issues
description: MultiUserClaw 项目问题汇总（精简索引，详细过程见 memory/ 目录下按主题分片的归档文件）
metadata:
  node_type: memory
  type: project
---

# MultiUserClaw 项目问题汇总（精简索引）

> 每条只留核心结论 + `file:line` + 状态。详细过程/方案评估/验证步骤 → `.claude/memory/` 目录下的 `archive-*.md`（5 主题分片）。入口：`.claude/memory/README.md`。

## 2. 渠道 UI 空壳（部分成立）
`proxy.py:352-375` channels/status|configured|config 返回空。飞书已走 device flow（第 33 节），旧 channels API 仍空。
## 4. agent 命名三层混乱
渠道 hardcode `agent:main`（`session.py:627-638`）；profiles 空返回虚拟 `hermes-agent`（`hermes_agents.py:384`）；原生 `deploy_copy/Agents/main/`。`SYSTEM_AGENT_IDS={main,manager,programmer,researcher,hr,doctor}`。
## 5. session 扁平存储
统一存 `/opt/data/sessions/`（全局），profile 下 `sessions/` 永远空。设计如此，非 bug。
## 6. 端口（gateway=9900 postgres=9901 frontend=3080 manage=3081 simple=3082）
8080/15432 被主机占。compose `ports` 是 append 非 replace，override 加端口不替换，直接改 `docker-compose.yml`。v0.17.0 新服云安全组只开 8000-9000 → override 追加 8180/8181/8182 外部映射（归档 N）。
## 7. LLM 模型 seed 只跑一次
`model_config.py:seed_model_config_from_env()` 仅 `model_provider_configs` 表空时跑。改 .env DEFAULT_MODEL 无效，改 DB/代码。
## 8. 单用户单容器
`Container.user_id` unique（`models.py:47`），一用户最多一 hermes 容器，所有 agent 共享。
## 11. 前端终端 = docker exec PTY 代理
`docker exec hermes-user-xxx sh -lc "bash -il"`（`proxy.py`），`tty=True`。workdir=`/opt/data`（`06f30b197`）。📖 归档 A。
## 15. hermes profile 目录
`${HERMES_HOME}/profiles/{name}/`（SOUL.md/workspace/memories/skills/cron），entrypoint.sh 从 `deploy_copy/Agents/*/` 同步。预置模板已裁到只剩 main。📖 归档 C。
## 16. 知识库（grep 非 RAG）
存 `profiles/{agent}/workspace/knowledge/`，`hermes_knowledge.py:283-285` 逐行 `in`。不自动注入 system prompt。`KnowledgeBase.tsx` 完整。
## 17. 文件管理（双根✅ / 敏感暴露⚠️）
浏览/读/上传/下载/删除/新建目录全 ✅。双根 `is_hermes_absolute_request`（`hermes_files.py:137`）从 `/` 浏览；相对走 /opt/data。双前缀 bug 已解决（`normalize` `removeprefix`）。⚠️ `.env`/`config.yaml`/`auth.json` 可见可删，未解决。
## 18. 模型配置：管理端唯一真入口
用户端 PUT `/models/config` 被 `proxy.py:418` 拒（前端假成功）。管理端 PUT `/api/admin/models`（`admin.py:404-457`）直写 DB。📖 归档 D。
## 19. 定时任务（✅ 可用）
`proxy.py` 透传 hermes `cron/scheduler.py`：列表/创建/删除/运行/启停。`CronJobs.tsx`。gateway 后台线程每 60s 调一次 `tick()`（`/opt/data/logs/agent.log`）。
## 20. Node 管理（❌ 不可用）
OpenClaw 设备配对，`proxy.py:382-383` 返回空，`Nodes.tsx` 永远空。
## 21. 容器生命周期
在跑时登录 4-7ms，重建 ~15s。`restart_policy: unless-stopped`，崩溃自重启。
## 25. 前端入口裁剪（✅）
`Sidebar.tsx` 注释 插件/Node/API设定/AI模型（同步注释 unused import）；`Channels.tsx` 只留 feishu。⚠️ `/plugins`/`/nodes`/`/api`/`/models` 路由未删，URL 可达。
## 29. runtime 统一 hermes，openclaw 废弃（2026-06-25）
`.env`+`config.py` 均 hermes。①runtime dead code 可清（`dedicated_openclaw.py`/`openclaw_compat.py`/`config.py` openclaw_*）；②平台基础设施勿删（openclaw-postgres/gateway/frontend/网络/卷/pgdata）。shared 半废弃（`proxy.py:430` 抛 409）。
## 30. hermes 镜像重建慢
`create_container`（`manager.py:738`）全量实例化 + 冷启动。`_container_matches_runtime`（:165-179）不比镜像版本 → rebuild 不触发容器重建，须显式删旧容器。📖 归档 I。
## 31. 容器空闲回收（配置有 / 未实现）
`config.py:83-84` `container_idle_pause/archive` 定义但零引用；无后台 scheduler。容器常驻，无 DB-Docker reconcile → 幽灵记录。**生产 50 人最大优化杠杆**（实现后内存 64G→32G）。
## 32. 删用户留孤儿卷
`destroy_container`（`manager.py:960`）保留卷 → 每用户留 2 孤儿卷。彻底删步骤见归档 I。
## 33. 飞书 device flow 网页化（✅ 已验证）
platform httpx 调飞书 device flow + 前端二维码轮询，根治 env 覆盖（原第 1 节）。改 `proxy.py`+`manager.py`(preserve_vars)+`Channels.tsx`+`api.ts`。📖 归档 J。
## 35. 飞书 SSO 架构 + roadmap（2026-06-26）
**SSO 不需重建 hermes**：认证全在 platform（`routes/auth.py`、`auth/service.py` JWT、`db/models.py` User），hermes 不参与（`manager.py:701-706` 仅透传 `INFOX_MED_TOKEN`）。只改 platform+frontend 重建即可。SSO 走网页 OAuth（`open.feishu.cn/open/authen`）≠ device flow，可能需独立飞书应用。
**roadmap**：✅ workdir/双根/hermes 镜像(v0.17.0)/SSO(TASK-1)；⏭️ 忽略（权限/敏感文件/模型假成功/P2 技术债）。
## 36. 默认模型缺陷（延后）/ agent 文件下载✅已修
① 默认模型：agent 用 `settings.default_model` 不读 DB `is_default`（`manager.py:134/456`），当前三者一致无故障，延后。② agent 文件下载 404 ✅ 已修（`normalize_hermes_read_path` 相对 `workspace` 补 `/`）。📖 归档 L。
## 39. hermes 输出截断：config.yaml 缺 model.max_tokens（2026-06-30 未修复）
写大 HTML 撞 `finish_reason=length` 被截断。根因：`_build_hermes_config_yaml`（`manager.py:221`）model 段无 max_tokens → 上游默认 4096。解法（plan 未执行）：`config.py` 加 `dedicated_hermes_default_max_tokens: int = 16384`（env 可调）+ `manager.py:221` 注入 `max_tokens`（<=0 不写回退）。新容器自动带；老容器需重建 + **新开会话**。plan 见 `~/.claude/plans/elegant-inventing-pillow.md`。
## 42. github.com HTTPS 被墙，git 操作走 SSH（2026-07-02 ✅）
服务器（58.87.64.156 国内）到 **github.com:443 被墙**（curl / ls-remote / git push 全 HTTP=000 超时），但：
- **api.github.com 通**（HTTP 200），gh CLI 全功能可用（登录 / API / `gh ssh-key`）
- **github.com:22 + ssh.github.com:443 TCP 通**
- DNS 正常（解析 20.205.243.166 = GitHub 真实 IP），非污染
- git push 只能走 github.com git 端点（被墙）或 SSH；**gh 无 push 命令，Git Data API 推不了 commit 历史**（只能单 commit 增量，推 17 commit 新分支不现实）

SSH key：`~/.ssh/id_ed25519_to_hosting`（公钥已注册 Mason-zy 账号）。**ssh 默认不加载非默认名 key**，必须 `-i` 显式指定。

**永久走 SSH**（已配）：① `git config --global url."git@github.com:".insteadOf "https://github.com/"`（所有 fetch/clone/push 全走 SSH）；② `~/.ssh/config` 加 `Host github.com / IdentityFile ~/.ssh/id_ed25519_to_hosting / IdentitiesOnly yes / ConnectTimeout 15`。配完 `git push origin` 自动走 SSH。

**排查教训**：`ssh -T` 报 Permission denied 时，先确认 ssh 是否加载了正确 key（非默认名 key 要 `-i`），别急着断定"key 没注册"。

**docker build 拉 GitHub 资源同样被墙**（2026-07-03，TASK-3）：`hermes-agent/Dockerfile` 拉 s6-overlay 用 `ADD`/`curl` 直连 `github.com` 会 i/o timeout（跟 git 同墙）。旧做法硬编码 `https://ghfast.top/` 代理（绕墙），但换能直连的构建环境（upstream CI / 官方构建）反而挂。**根治**：改 `ARG GITHUB_MIRROR=""`，URL 拼 `${GITHUB_MIRROR}https://github.com/...`，默认空走官方、CN 构建带 `--build-arg GITHUB_MIRROR=https://ghfast.top/`。⚠️ CN 服务器重建 hermes 镜像（含 bridge）**务必带这个 build-arg**，否则 s6-overlay 拉取超时、构建挂。同模式可复用：凡 docker build 要拉 GitHub 资源的，都用 ARG 注入镜像前缀，别硬编码代理。

## 43. 远程仓库职责（2026-07-02）
- **origin**（`Mason-zy/MultiUserClaw-private` 私有库）= 主开发库，日常 push/pull 都在这
- **fork**（`Mason-zy/MultiUserClaw` 公开库）= **专门给 upstream 提 PR 用**，别把 main 的业务偏离推上去（只推 PR 分支）。用户原话「这个是专门用来提 PR 的」
- **upstream**（`johnson7788/MultiUserClaw`）= 上游，只 pull/merge，不 push
- **venus**（`VenusFennn`）= 旧协作镜像，`git-branch-diff` 默认排除（`--all-remotes` 可恢复）

分支清理约定：升级/PR 合入 main 后，对应工作分支（如 `upgrade-v017`、`fix/*`）在本地 + origin 私有库删除；`backup-*` 留作回滚保险。

## 44. 切模型操作（三层，改一不可）（2026-07-03）

**Why**：`glm-5.1` 余额不足 → 全容器 LLM 调不通 → 飞书对话全挂。模型切换不只是一个文件——涉及 litellm 表、.env 全局默认、运行中容器 config.yaml 三层。

**三层操作**：
1. **litellm 表**（让 gateway 认识这个模型）：`model_provider_configs` 的 JSON `models` 数组加目标模型。`UPDATE model_provider_configs SET models = (models::jsonb || '[{"id":"deepseek-v4-pro-anthropic","name":"DeepSeek V4 Pro","enabled":true}]'::jsonb)::json WHERE id='openai';`。验证：`SELECT models FROM model_provider_configs WHERE id='openai'`。改完 `docker compose up -d gateway` 重建生效。注意 `json || jsonb` 语法不兼容，要 cast 一致。
2. **`.env` 全局默认**：`DEFAULT_MODEL=openai/deepseek-v4-pro-anthropic`。gateway 重启后新容器用这值写 config.yaml（`container/manager.py:221-236`）。老容器不受影响。
3. **每个运行中容器 config.yaml**（不会自动同步）：`sed -i 's/default: openai\/glm-5.1/default: openai\/deepseek-v4-pro-anthropic/' /opt/data/config.yaml`。改完 **下一条消息立即生效**（agent `_create_agent` 每次新 run 读盘，`api_server.py:1102-1103`），不需重启。

**验证**：直调 fjbigmodel 测 key 能用再切（`curl fjbigmodel.fjdac.cn/v1/chat/completions`），切完看 `agent.log` 确认 `conversation turn` 的 `model=` 生效 + `Turn ended` 成功（非 `API call failed`）。这次踩的坑：`glm-5` key 白名单里有但 litellm 表没配 → `no healthy deployments`；`gpt-5.4` 表里有但旧 key 余额不足 → 502。最终 `deepseek-v4-pro-anthropic` 全通。

## 45. 撤回飞书 bot 消息（2026-07-03）

**Why**：手动补推销售日报时发了三批共 40 条消息，需要撤回后两次（40 条）。

**关键约束**：撤回必须用**发消息的那个 bot** 的 tenant_access_token，不能跨 bot。

**操作**：`DELETE https://open.feishu.cn/open-apis/im/v1/messages/{message_id}`，Header `Authorization: Bearer <tenant_access_token>`。token 来源：①从目标容器 `/opt/data/.env` 读 `FEISHU_APP_ID`/`FEISHU_APP_SECRET`；②调 `/auth/v3/tenant_access_token/internal` 拿 `tenant_access_token`。message_id 从 `push_card.py` stdout 的 `code=0 success mid=om_xxx` 提取。`lark-cli` 也可用（`lark-cli im messages delete --message-id <mid> --as bot`），但当前 lark-cli 配置的是平台 bot 非 Alice bot，所以只能从容器内直调 API。

**现成脚本**：`/tmp/revoke.py`（alice 容器内），接受 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 环境变量 + 硬编码 mid 列表，批量 DELETE 并统计 ok/fail。

## 46. vision 配置注入（2026-07-03 ✅）— `manager.py:221/465` auxiliary.vision 段，api_key 从容器 env NANOBOT_PROXY__TOKEN 注入（commit a289786）；存量 3 容器手改，新容器自动带。📖 归档 Q
## 47. audit_log 双写（2026-07-03 ✅ 代码 ⏳ 待部署）— `service.py:770-782/801-813` 删冗余 write_audit_log，merge 到 main；gateway 镜像重建才生效。📖 归档 Q
## 48. baime 全流程实战（2026-07-03）— 两 task 跑通 Proposal/Plan review + loop-backlog worktree 隔离实现。踩坑：marketplace dir 被删 + Agent API Error。📖 归档 Q

## 关联记忆
- [[multiuserclaw-agent-naming]] [[multiuserclaw-channel-ui]]
- 详细过程归档 → `.claude/memory/archive-*.md`（入口 `.claude/memory/README.md`）
