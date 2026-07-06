---
name: multiuserclaw-issues
description: MultiUserClaw 项目问题汇总（精简索引，详细过程见 memory/ 目录下按主题分片的归档文件）
metadata:
  node_type: memory
  type: project
---

# MultiUserClaw 项目问题汇总（精简索引）

> 每条核心结论 + `file:line` + 状态。详细过程 → `.claude/memory/archive-*.md`（5 主题分片，入口 `README.md`）。

## 2. 渠道 UI 空壳
`proxy.py:352-375` channels 返回空。飞书走 device flow（#33），旧 API 仍空。
## 4. agent 命名三层
hardcode `agent:main`（`session.py:627`）；profiles 空返虚拟 `hermes-agent`（`hermes_agents.py:384`）；原生 `deploy_copy/Agents/main/`。`SYSTEM_AGENT_IDS={main,manager,programmer,researcher,hr,doctor}`。
## 5. session 扁平
统一 `/opt/data/sessions/`（全局），profile 下空。设计如此非 bug。
## 6. 端口
gateway=9900 postgres=9901 frontend=3080 manage=3081 simple=3082（8080/15432 主机占）。compose `ports` append 非 replace，直接改 `docker-compose.yml`。v0.17.0 安全组 8000-9000 → override 追加 8180/8181/8182。
## 7. 模型体系（整合 #7/18/36/39/44/46）
两层：主模型（对话）+ vision（看图代理）。每容器独立 `/opt/data/config.yaml`，agent 每 run 读盘（`api_server.py:1102`），**改完下条消息生效不重启**。
- **主模型**：当前 `deepseek-v4-pro-anthropic`。`.env DEFAULT_MODEL` → `config.py:40` → `manager.py:236`。缺陷：① `settings.default_model` 不读 DB `is_default`（`manager.py:134/456`）② `seed_model_config_from_env()` 仅表空跑 ③ 用户端 `/models/config` 假成功（`proxy.py:418`），管理端 `admin.py:404` 真入口 ④ `manager.py:221` 缺 max_tokens（4096 截断，#39 未修）。
- **vision**：当前 `gpt-5.4`（glm 系列不支持识图会瞎编）。`config.py:58 dedicated_hermes_default_vision_model` → `manager.py:241`。hermes 原生分离模式（`image_routing.py:340` 有 auxiliary.vision → 强制 text 管道：vision 看图→文字→主模型），我们只补了 auxiliary.vision 段，路由没改。演变：无配置报错→glm-5.1 瞎编→gpt-5.4。
- **切换三层**：litellm 表 SQL + restart gateway / `.env`（仅新容器）/ 容器 config.yaml sed（下条消息）。切主模型后**必须 /stop 卡住 turn 再发**（running turn 锁旧 model）。
## 8. 单用户单容器
`Container.user_id` unique（`models.py:47`）。
## 11. 前端终端 = docker exec PTY
`docker exec hermes-user-xxx sh -lc "bash -il"`（`proxy.py`），workdir `/opt/data`。📖 归档 A
## 15. hermes profile 目录
`${HERMES_HOME}/profiles/{name}/`（SOUL.md/workspace/memories/skills/cron），entrypoint.sh 从 `deploy_copy/Agents/*/` 同步。📖 归档 C
## 16. 知识库（grep 非 RAG）
`profiles/{agent}/workspace/knowledge/`，`hermes_knowledge.py:283` 逐行 `in`，不注入 system prompt。
## 17. 文件管理
双根浏览/读写/上传/下载 ✅（`hermes_files.py:137`）。⚠️ `.env`/`config.yaml`/`auth.json` 可见可删未解决。
## 19. 定时任务 ✅
`proxy.py` 透传 hermes `cron/scheduler.py`，gateway 后台每 60s `tick()`。
## 20. Node 管理 ❌
`proxy.py:382` 返回空，`Nodes.tsx` 永远空。
## 21. 容器生命周期
登录 4-7ms，重建 ~15s。`restart: unless-stopped`。
## 25. 前端入口裁剪 ✅
`Sidebar.tsx`/`Channels.tsx` 已裁。⚠️ `/plugins`/`/nodes`/`/api`/`/models` 路由未删 URL 可达。
## 29. runtime 统一 hermes，openclaw 废弃
`.env`+`config.py` 均 hermes。runtime dead code 可清（`dedicated_openclaw.py`/`openclaw_compat.py`），平台基础设施勿删（postgres/gateway/frontend/网络/卷）。shared 半废弃（`proxy.py:430` 抛 409）。
## 30. hermes 镜像重建慢
`create_container`（`manager.py:738`）全量实例化。`_container_matches_runtime`（:165）不比镜像版本 → rebuild 不触发容器重建，须显式删旧容器。📖 归档 I
## 31. 容器空闲回收（配置有/未实现）
`config.py:83` 定义零引用，无 scheduler。**生产 50 人最大优化杠杆**（64G→32G）。
## 32. 删用户留孤儿卷
`destroy_container`（`manager.py:960`）保留卷 → 每用户 2 孤儿卷。📖 归档 I
## 33. 飞书 device flow ✅
platform httpx 调 device flow + 前端二维码轮询。改 `proxy.py`+`manager.py`+`Channels.tsx`+`api.ts`。📖 归档 J
## 35. 飞书 SSO 架构
认证全在 platform（`routes/auth.py`），hermes 不参与（`manager.py:701` 仅透 token）。只改 platform+frontend 重建。
## 36. agent 文件下载 ✅
`normalize_hermes_read_path` 相对 workspace 补 `/` 修复 404。📖 归档 L
## 42. github.com 被墙，git 走 SSH
github.com:443 被墙（:22 通），api.github.com 通。已配 `git config --global url.git@github.com:.insteadOf https://github.com/` + `~/.ssh/config`（key `~/.ssh/id_ed25519_to_hosting`，非默认名要 `-i`）。docker build 拉 github 同墙 → `ARG GITHUB_MIRROR`（`Dockerfile:66`）CN 带 `https://ghfast.top/`。
## 43. 远程仓库职责
- **origin**（`Mason-zy/MultiUserClaw-private`）= 主开发库
- **fork**（`Mason-zy/MultiUserClaw`）= 提 PR 给 upstream 用（只推 PR 分支）
- **upstream**（`johnson7788/MultiUserClaw`）= 上游只 pull，**所有 bugfix PR 只提这里**
- **NousResearch/hermes-agent** = **忽视不提**（上游不 review，用户定只关注 johnson7788）
- **Mason-zy/hermes-agent** fork = 闲置可删
- venus（`VenusFennn`）= 旧镜像可忽略
## 45. 撤回飞书 bot 消息
用发消息 bot 的 tenant_access_token，`DELETE /open-apis/im/v1/messages/{mid}`。token 从容器 `/opt/data/.env` 读 APP_ID/SECRET。脚本 `/tmp/revoke.py`。📖 归档
## 47. audit_log 双写 ✅代码 ⏳待部署
`service.py:770/801` 删冗余 write_audit_log，gateway 镜像重建生效。📖 归档 Q
## 48. baime 全流程 ✅
feature-to-backlog + loop-backlog 跑通（worktree 隔离 + DoD 验证 + merge）。📖 归档 Q
## 49. 飞书 @all + home channel 修复（2026-07-06 ✅）
- **@all 回复**（上游 #33723 设计）：`adapter.py:4184` `_mentions_self` 删 `@_all→True`。commit `62da7583c` + 3 容器 docker cp。
- **home channel 反复弹**（上游 #10581）：`run.py:10028` 加 `self.config` 回退（`/sethome` 写 .env+self.config 但 os.getenv 拿不到）。commit `4a7234c90` + 3 容器 docker cp。
- **持久性**：①② 在镜像层（`/opt/hermes/`，restart 不丢，删容器重建丢）；③ 模型 sed 在卷层（永久）。根治：重建 hermes 镜像（2026-07-06 进行中）。
- **sethome**：每 bot 一个默认投递点，不影响对话（按 chat_id 分会话），不影响销售日报（脚本 hardcode `oc_90810ad2` + `--route`）。
- **PR**：johnson7788 #57/#58（NousResearch #59347/#59348 忽视）。
## 50. docker root 迁数据盘（2026-07-06 ✅）
vda 50G 紧 → vdb 500G（`/opt/applications`）。docker+containerd 都迁 `/opt/applications/data/`。
- **踩坑**：docker 用 containerd snapshotter（`docker info` 的 `driver-type: io.containerd.snapshotter.v1`），**镜像层在 `/var/lib/containerd`（18G）不在 `/var/lib/docker`（793M）**，迁移必须连 containerd 一起，否则镜像丢。
- **步骤**：停 docker+containerd → `rsync /var/lib/{docker,containerd}/ /opt/applications/data/{docker,containerd}/` → docker `daemon.json` 加 `data-root` + containerd systemd override `/etc/systemd/system/containerd.service.d/override.conf` 加 `ExecStart=/usr/bin/containerd --root=/opt/applications/data/containerd`（无 config.toml，socket 仍走 `/run/containerd`）→ 启动，8 容器 unless-stopped 自动恢复。
- **待做**：旧 `/var/lib/{docker,containerd}` 观察稳定后删腾系统盘 ~30G。
- **build arg 三件套**（`Dockerfile:31/32/66`，不传走官方源 CN 慢/挂）：`GITHUB_MIRROR=https://ghfast.top/`（s6-overlay）+ `APT_DEBIAN_MIRROR=https://mirrors.ustc.edu.cn/debian` + `APT_SECURITY_MIRROR=https://mirrors.ustc.edu.cn/debian-security` + `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。build 不影响运行容器（锁定旧镜像 ID）。

## 关联记忆
- [[multiuserclaw-agent-naming]] [[multiuserclaw-channel-ui]]
- 详细过程归档 → `.claude/memory/archive-*.md`（入口 `README.md`）
