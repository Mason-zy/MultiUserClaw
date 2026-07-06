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
## 7. 模型体系（2026-07-03 整合 #7/#18/#36/#39/#44/#46）

> 主模型（对话推理）+ vision 模型（看图代理）两层，各走各的配置链。每个容器独立 config.yaml，改完下条消息即生效、不重启。

### 配置数据流

```
.env / docker-compose environment                  litellm 表 (model_provider_configs)
  │  DEFAULT_MODEL=openai/deepseek-v4-pro-anthropic    │  使 gateway 认模型
  │  PLATFORM_DEDICATED_HERMES_DEFAULT_VISION_MODEL     │  docker compose restart gateway 才刷
  │     =openai/gpt-5.4                                 │
  ▼                                                     ▼
config.py (Settings)                              gateway (litellm 代理)
  │  default_model: str                                │
  │  dedicated_hermes_default_vision_model             │
  ▼                                                     │
manager.py _build_hermes_config_yaml() ────────────────┘
  │  生成 /opt/data/config.yaml:
  │    model.default: openai/deepseek-v4-pro-anthropic
  │    auxiliary.vision.model: openai/gpt-5.4
  ▼
容器 /opt/data/config.yaml ──→ agent 每 run 读盘 (api_server.py:1102)
  │                             改完下条消息立即生效，不重启
  ▼
hermes 原生路由 (image_routing.py:340)
  │  有 auxiliary.vision → 强制分离 (vision模型看图→文字→主模型)
  │  无 auxiliary.vision → 检查主模型 supports_vision → native/text
```

### 三层生效时机

| 层 | 位置 | 怎么改 | 生效时机 | 影响范围 |
|---|------|--------|---------|---------|
| 1 | litellm 表 `model_provider_configs` | SQL UPDATE + `docker compose restart gateway` | 重启后 | 让 gateway 认识这个模型 |
| 2 | `.env` `DEFAULT_MODEL` | 改 .env | 下次 compose up / 新容器 | **仅新容器**，老容器不受影响 |
| 3 | 容器内 `/opt/data/config.yaml` | `docker exec sed` | **下条消息立即生效** | 仅该容器 |

### 主模型 (model.default)

- **当前**：`openai/deepseek-v4-pro-anthropic`（#44，glm-5.1 余额不足→全容器切）
- **配置文件**：`config.py:40` `default_model` → `manager.py:236` 写容器 config.yaml
- **缺陷**：① `settings.default_model` 不读 DB `is_default`（`manager.py:134/456`，#36 延后）② `model_config.py:seed_model_config_from_env()` 仅表空时跑，改 .env 不刷新（#7）③ 用户端 PUT `/models/config` 被 `proxy.py:418` 拒（#18，管理端 `admin.py:404` 是真入口）
- **切换操作**：见 #44 三层步骤（litellm 表 SQL + .env + 每个容器 sed）
- **max_tokens 缺失**：`manager.py:221` model 段无 max_tokens → 上游默认 4096，写大 HTML 截断（#39 未修，plan 有）

### Vision 模型 (auxiliary.vision)

- **当前**：`openai/gpt-5.4`（今天从 glm-5.1 切过来，#46）
- **配置文件**：`config.py:58` `dedicated_hermes_default_vision_model` → `manager.py:241` 写容器 config.yaml
- **架构**：hermes 原生两阶段分离。我们只补了 missing piece（manager.py 注入 auxiliary.vision 段），路由逻辑 `image_routing.py:340` 一行没改
- **演变**：无配置（报错）→ glm-5.1（不看图瞎编）→ gpt-5.4（真看图）
- **注意**：当前所有容器强制分离模式，即使主模型支持 vision（如 gpt-5.4）也会浪费一次辅助调用；切 vision-capable 主模型需删 auxiliary.vision 段走 native
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
## 36. agent 文件下载 ✅已修 — `normalize_hermes_read_path` 相对 `workspace` 补 `/` 修复 404。📖 归档 L
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
- **upstream**（`johnson7788/MultiUserClaw`）= 上游，只 pull/merge，不 push。**所有 bugfix PR 只提这里**
- **NousResearch/hermes-agent**（hermes 本体上游）= **忽视，不提 PR**（#59347/#59348 留置不管，上游不 review）；hermes-agent 子目录 bugfix 也只提 johnson7788。用户原话「忽视了 以后只关注 johnson7788」
- **Mason-zy/hermes-agent**（2026-07-06 新建 fork）= 闲置，可删
- **venus**（`VenusFennn`）= 旧协作镜像，`git-branch-diff` 默认排除（`--all-remotes` 可恢复）

分支清理约定：升级/PR 合入 main 后，对应工作分支（如 `upgrade-v017`、`fix/*`）在本地 + origin 私有库删除；`backup-*` 留作回滚保险。

## 45. 撤回飞书 bot 消息（2026-07-03）

**Why**：手动补推销售日报时发了三批共 40 条消息，需要撤回后两次（40 条）。

**关键约束**：撤回必须用**发消息的那个 bot** 的 tenant_access_token，不能跨 bot。

**操作**：`DELETE https://open.feishu.cn/open-apis/im/v1/messages/{message_id}`，Header `Authorization: Bearer <tenant_access_token>`。token 来源：①从目标容器 `/opt/data/.env` 读 `FEISHU_APP_ID`/`FEISHU_APP_SECRET`；②调 `/auth/v3/tenant_access_token/internal` 拿 `tenant_access_token`。message_id 从 `push_card.py` stdout 的 `code=0 success mid=om_xxx` 提取。`lark-cli` 也可用（`lark-cli im messages delete --message-id <mid> --as bot`），但当前 lark-cli 配置的是平台 bot 非 Alice bot，所以只能从容器内直调 API。

**现成脚本**：`/tmp/revoke.py`（alice 容器内），接受 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 环境变量 + 硬编码 mid 列表，批量 DELETE 并统计 ok/fail。

## 47. audit_log 双写（2026-07-03 ✅ 代码 ⏳ 待部署）— `service.py:770-782/801-813` 删冗余 write_audit_log，merge 到 main；gateway 镜像重建才生效。📖 归档 Q
## 48. baime 全流程实战（2026-07-03）— 两 task 跑通 Proposal/Plan review + loop-backlog worktree 隔离实现。踩坑：marketplace dir 被删 + Agent API Error。📖 归档 Q
## 49. 飞书 @all 触发回复 + home channel 反复弹提示（2026-07-06 ✅）

**问题 1（@all 回复，上游设计）**：`adapter.py:4184-4188` `_mentions_self` 对含 `@_all` 的消息 `return True`，飞书 @所有人被当成 bot 被提及 → `:4127` require_mention 门控通过 → bot 回复。注释写死"@_all is Feishu's @everyone placeholder"是有意为之。另两条路径（`_message_mentions_bot` 按 ID 严格匹配 / `_post_mentions_bot` 只看 `is_self`）不会误判 @all。**修复**：删 `:4187-4188` 两行，仅改容器内 `/opt/hermes/plugins/platforms/feishu/adapter.py`（用户定单用户修复，**不进仓库**），3 容器都改 + 重启 gateway 生效。

**问题 2（home channel 反复弹，上游 bug）**：`run.py:10025-10044` 的"📬 No home channel"提示查 `os.getenv(env_key)`，但 `/sethome`（`slash_commands.py:2102`）调 `save_env_value` 只写 `.env` 文件 + `self.config`，不更新 `os.environ`。`.env` 要进程重启才进 os.environ → 没重启时每次新会话（`not history`）反复弹（注释说 one-time，实为 every-new-conversation）。**修复**：`run.py:10028` 加 `self.config.platforms[platform].home_channel` 回退检查（commit 4a7234c90，LOCAL 标记，进仓库 + 3 容器 docker cp + 重启）。ce545995 容器铁证：`.env` 有 `FEISHU_HOME_CHANNEL`，`/proc/1/environ` 没有。

⚠️ **改动持久性矩阵（2026-07-06）**：容器卷映射——`/opt/data`（config/.env/skills，**卷层**，重建保留）/ `/workspace`（**卷层**）/ `/opt/hermes/`（代码，**镜像层**，重建从镜像恢复）。本次三处改动分层：
  - ① run.py home channel 修复（commit 4a7234c90，仓库有）：docker cp 进 `/opt/hermes/gateway/run.py`（镜像层）
  - ② adapter.py @all 删两行：docker cp 进镜像层 + **进仓库**（commit 62da7583c，带 LOCAL 注释）
  - ③ alice 主模型 glm-5.1→gpt-5.4：sed `/opt/data/config.yaml`（**卷层**，永久）

  | 场景 | ① run.py | ② adapter.py | ③ model |
  |---|---|---|---|
  | `docker restart`（进程重启） | ✅在 | ✅在 | ✅在 |
  | 删容器重建（destroy+create） | ❌丢 | ❌丢 | ✅在 |
  | **新用户**（manager.py 从镜像建容器） | ❌无 | ❌无 | vision=gpt-5.4✅，主模型看 settings.default_model |

  **根治**：把 ①② 打进 hermes 镜像。①② 已都在仓库（run.py `4a7234c90`、adapter.py `62da7583c`）→ 重建 hermes 镜像（⚠️ 必带 `--build-arg GITHUB_MIRROR=https://ghfast.top/` 否则 s6-overlay 超时）→ 老容器删了重建（`_container_matches_runtime` 不比镜像版本，#30）。重建镜像前：①② 对新用户不生效（镜像旧），老用户删容器重建后丢失需重做。

**sethome 逻辑澄清**：home channel 是 hermes「默认投递 fallback」（未指定目标的消息/系统通知/cron 结果归宿），每个 bot 一个、`/sethome` 覆盖非叠加。**与会话隔离无关**——hermes 按 `chat_id` 分会话（session key = `agent:main:feishu:<dm|group>:<chat_id>:<on_xxx>`），每个群/单聊独立历史，bot 可同时在任意多 chat 对话。sethome 不限制对话地点。销售日报 cron（`deliver: local` + 脚本 hardcode `TEAM_CHAT=oc_90810ad2...` + `--route`）完全不走 home，sethome 到任何群都不影响日报推送。sethome 唯一实际效果：消「No home channel」提示 + 决定系统通知归宿。

**模型排查教训（#44 漏网）**：alice 容器（9c0d224f）主模型一直是 glm-5.1，#44「全容器切 deepseek」时漏切/被改回 → glm-5.1 余额耗尽（`[1113]`）→ LLM 全挂 bot 不回复。切模型 sed 后**必须 /stop 当前卡住的 turn 再发新消息**（running turn 锁定旧 model，不重读 config；agent `_create_agent` 每**新** run 读盘）。验证：agent.log `conversation turn model=` + `Turn ended reason=text_response`。最终 alice 切 gpt-5.4（deepseek 直调也 None，glm 系列全余额不足）。📖 归档 Q

**bugfix PR 只提 johnson7788/MultiUserClaw**（2026-07-06）：[#57](https://github.com/johnson7788/MultiUserClaw/pull/57)（@all）、[#58](https://github.com/johnson7788/MultiUserClaw/pull/58)（home channel）。**NousResearch/hermes-agent 上游忽视不管**（#59347/#59348 留置），用户定「以后只关注 johnson7788」；`Mason-zy/hermes-agent` fork 闲置可删。提 PR 技巧：hermes-agent 大仓库 clone 超时 → `gh api contents` PUT 单文件（--input JSON 避免 ARG_MAX）；MultiUserClaw 本地有 clone → `git worktree` 隔离基于 upstream/main 建分支。注释风格见 CLAUDE.md（英文 + issue 号 + @Mason-zy，不带 LOCAL）。

## 50. docker root 迁移到 500G 数据盘（2026-07-06 ✅）

系统盘 vda 50G 紧张（65%），数据盘 vdb 500G 闲置（3%，挂 `/opt/applications`）。docker root + containerd 都迁到 `/opt/applications/data/`。

**关键发现（踩坑）**：docker 用 containerd snapshotter 模式（`docker info` 显示 `driver-type: io.containerd.snapshotter.v1`），**镜像层在 `/var/lib/containerd`（18G），不在 `/var/lib/docker`（只 793M metadata + volumes）**。第一次只 rsync `/var/lib/docker`，启 docker 用新 data-root 后镜像层找不到（幸好回滚验证发现）。**迁移 docker root 必须连 containerd 一起迁**，否则镜像丢。

**迁移步骤**：① 备份 daemon.json + `systemctl cat containerd > 备份` ② 停 `docker docker.socket containerd` ③ `rsync -aP /var/lib/{docker,containerd}/ /opt/applications/data/{docker,containerd}/` ④ docker `/etc/docker/daemon.json` 加 `"data-root": "/opt/applications/data/docker"` ⑤ containerd systemd override `/etc/systemd/system/containerd.service.d/override.conf`：`[Service]\nExecStart=\nExecStart=/usr/bin/containerd --root=/opt/applications/data/containerd`（containerd 无 config.toml，用 `--root` 参数最简，socket 仍走默认 `/run/containerd`） ⑥ `daemon-reload` + 启 containerd + docker ⑦ 8 容器 `unless-stopped` 自动恢复。

**验证**：`docker info` Root Dir 新路径 + `docker images` 镜像完整（15 个）+ 8 容器 Up + postgres healthy + 卷挂载指数据盘 + gateway/hermes 功能正常。

**待做**：旧 `/var/lib/docker` + `/var/lib/containerd` 还在系统盘（冗余，回滚保险），**观察稳定几小时后删**腾系统盘 ~30G。

**收益**：以后 build hermes 镜像不怕磁盘满（500G 数据盘），根治上次 build 崩系统的磁盘满根因（系统盘 50G → 磁盘满 → postgres 写失败 → 连锁崩）。重建 hermes 镜像现在可安全做（代做清单"bridge 镜像 edge-tts"也可一并）。

## 关联记忆
- [[multiuserclaw-agent-naming]] [[multiuserclaw-channel-ui]]
- 详细过程归档 → `.claude/memory/archive-*.md`（入口 `.claude/memory/README.md`）
