# MultiUserClaw - 多用户 AI SaaS Hermes Agent 平台

基于 Hermes 改造的轻量级 AI 助手框架，可以快速打造商用 SaaS 平台，支持多租户隔离部署、多平台渠道接入、工具调用、定时任务和 Web 实时通信。

**在线体验地址**：https://ai.infox-med.com:13080/ （直接注册即可使用）
当前默认内核后端：Hermes Agent

---

## 📌 版本分支说明

- **main 分支**：当前主分支，基于hermes 6月底版本，因为hermes比openclaw快很多，所以全面切换为hermes分支
- **openclaw 分支**：旧主分支（已归档），基于 OpenClaw 2026.5.10
- **nanobot014v3 分支**：nanobot 的 0.1.4 post v3 版本

---

## 🎯 核心原理

**架构设计**：新增 platform 作为控制容器的网关，每个用户单独创建容器进行管理。

```
Frontend (前端界面) → Platform (平台网关) → Hermes Agent (AI 引擎)
```

- **Frontend**：前端页面进行显示，调用 platform 进行交互
- **Platform**：控制容器管理，调用 hermes agent 进行 AI 交互
- **Hermes Agent**：基于 Hermes 的 AI Agent 运行时

**升级 Hermes**：重建 hermes 镜像即可

---

## 📝 最新更新

main 分支已全面切换为 Hermes Agent，相比之前的 OpenClaw，Hermes 具有更快的启动速度和响应性能。

---

## 📖 目录

1. [功能特性](#功能特性)
2. [界面预览](#界面预览)
3. [运行流程概览](#运行流程概览)
4. [多租户部署（Docker Compose）](#多租户部署docker-compose)
5. [单用户本地运行](#单用户本地运行)
6. [整体架构](#整体架构)
7. [核心组件详解](#核心组件详解)
8. [安全设计](#安全设计)
9. [前端](#前端)
10. [deploy_copy — 预置 Agent 与技能](#deploy_copy--预置-agent-与技能)
11. [文件索引](#文件索引)
12. [API 调用示例](#api-调用示例)
13. [升级 Hermes](#升级-hermes)
14. [容器端口映射](#容器端口映射)
15. [渠道配置](#渠道配置)
16. [可选改进建议](#可选改进建议)
17. [相关文档](#相关文档)
18. [联系方式](#联系方式)

---

## ✨ 功能特性

本平台是一个功能丰富的多租户 AI 助手平台，支持以下核心功能：

### 🤖 AI Agent 管理
- 创建、配置和管理多个 AI Agents
- 每个 Agent 独立的对话上下文
- Agent 身份设置（名称、Emoji 图标）
- Agent 详情查看和删除

### 💬 智能对话
- WebSocket 实时通信
- Markdown 消息渲染（支持代码高亮）
- 斜杠命令自动补全
- 多会话管理
- 语音输入支持
- 文件/图片上传发送

### ⏰ 定时任务 (Cron Jobs)
- 固定间隔执行
- Cron 表达式调度
- 单次定时执行
- 任务启用/禁用
- 手动立即执行
- 执行结果通知（可选发送到渠道）

### 📚 知识库
- 每个 Agent 独立的知识库目录
- 支持上传文档、PDF、图片、数据文件
- 文件夹创建和管理
- 文件预览（支持文本、代码、JSON 等）
- 文件下载和删除

### ⚡ 技能商店 (Skills)
- 搜索和安装来自 skills.sh 的 AI 技能
- 技能启用/禁用
- 内置技能 + 用户自定义技能

### 🔌 多渠道支持
- Telegram
- Discord
- Email (SMTP)
- WhatsApp Web
- Signal
- Slack
- iMessage
- 其他扩展渠道
- 配置文档：https://my.feishu.cn/wiki/KfTlwurh7ix0PHkQmHic2L0Snue

### 🔑 API 访问
- API Token 生成和管理
- 支持命令行调用 Agent
- 会话复用
- 外部系统集成

### 🧠 多模型支持

| 提供商 | 模型示例 |
|--------|---------|
| DashScope | qwen3-coder-plus, qwen-turbo |
| Anthropic | claude-sonnet-4-5, claude-opus-4-5 |
| OpenAI | gpt-4o, gpt-4o-mini, o3-mini |
| DeepSeek | deepseek-chat, deepseek-reasoner |
| AiHubMix | aihubmix/模型名 |
| Evolink | evolink/gpt-5.2, evolink/deepseek-chat |
| OpenRouter | openrouter/任意模型（兜底） |

### 📊 仪表盘
- Agent 总数统计
- 会话总数统计
- 技能总数统计
- Agent 状态概览

### 📁 文件管理
- 工作空间文件浏览
- 文件上传/下载
- 目录创建/删除

### ⚙️ 系统管理
- 用户管理
- 渠道配置
- AI 模型配置
- 审计日志
- 系统设置

### 🏢 多租户隔离
- 每个用户独立 Docker 容器
- 容器级资源隔离（2GB RAM, 4 CPU）
- 按需创建，空闲自动暂停
- 数据完全隔离

---

## 🖼️ 界面预览

### 仪表盘与聊天界面

![dashboard.png](doc/dashboard.png)
![chat.png](doc/chat.png)
![multi_users_docker.png](doc/multi_users_docker.png)

### 技能管理

![skill_create1.png](doc/skill_create1.png)
![skill_create2.png](doc/skill_create2.png)
![skill_page.png](doc/skill_page.png)

### 聊天与管理界面

![chat.png](doc/chat.png)
![chat2.png](doc/chat2.png)
![管理界面.png](doc/%E7%AE%A1%E7%90%86%E7%95%8C%E9%9D%A2.png)

### 容器修复

![一键容器修复.png](doc/%E4%B8%80%E9%94%AE%E5%AE%B9%E5%99%A8%E4%BF%AE%E5%A4%8D.png)

### 定时任务管理

![cron_job.png](doc/cron_job.png)
![cron_status.png](doc/cron_status.png)

### Agent 管理

![create_agent.png](doc/create_agent.png)

### 技能商店

![skill_marketplace.png](doc/skill_marketplace.png)

### 插件管理

![plugins.png](doc/plugins.png)

### 浏览器访问

![agent_browser1.png](doc/agent_browser1.png)
![agent_browser2.png](doc/agent_browser2.png)

### 管理界面

![manage_frontend.png](doc/manage_frontend.png)

### API 调用示例

![使用curl命令.png](doc/%E4%BD%BF%E7%94%A8curl%E5%91%BD%E4%BB%A4.png)
![指定调用skill功能.png](doc/%E6%8C%87%E5%AE%9A%E8%B0%83%E7%94%A8skill%E5%8A%9F%E8%83%BD.png)

### vLLM 支持

![vllm_support_log.png](doc/vllm_support_log.png)

---

## 🔄 运行流程概览

本项目的核心思路：**用 Hermes 作为每个用户的 AI Agent 运行时**，通过容器化方式将 Hermes 接入到平台的多租户体系中。

### 一条消息的完整旅程

```
用户在浏览器输入消息
    |
    v
[Frontend] Vite+React (端口 3080)
    | WebSocket 连接
    v
[Platform Gateway] FastAPI (端口 8080) --对应platform目录和项目
    | 1. JWT 认证
    | 2. 查找/启动用户容器
    | 3. WebSocket 代理
    v
[用户容器] — 每个 dedicated 用户一个独立 Docker 容器
    |
    |  容器内部结构:
    |  ┌─────────────────────────────────────────┐
    |  │  Hermes API Server (端口 18080)           │
    |  │    - HTTP / SSE API                       │
    |  │    - Session / Run 管理                   │
    |  │    - 工具调用 (bash/文件/搜索等)           │
    |  │    - Skills 系统                          │
    |  └─────────────────────────────────────────┘
    |
    | Agent 需要调用 LLM 时:
    v
[Platform Gateway] /llm/v1/chat/completions
    | 1. 验证容器 Token
    | 2. 检查用户配额
    | 3. 根据模型名匹配 Provider
    | 4. 注入真实 API Key
    v
[LLM 提供商] (Anthropic / OpenAI / DashScope / DeepSeek / ...)
    |
    | 响应沿原路返回
    v
用户在浏览器看到回复
```

核心转发兼容 API 的流程
```  具体流程：

   1. Frontend (前端)
      - 运行在 3080 端口
      - Vite 配置将 /api 代理到 http://localhost:8080（gateway）

   2. Gateway / Platform (平台后端)
      - 运行在 8080 端口，由 ./platform 构建
      - 处理认证、用户管理、数据库
      - 对于 /api/openclaw/* 和 /api/shared-openclaw/* 路径，通过 platform/app/api_compat/openclaw_compat.py 调用当前 runtime backend

   3. Hermes Runtime (用户容器内或 shared runtime)
      - Dedicated 用户有独立 Docker 容器；shared 用户共用 shared runtime，并由平台校验 session/run 归属
      - Hermes API 服务运行在 18080 端口（dedicated）或 8080 端口（shared）
      - 提供 sessions、runs、skills、workspace 等 runtime 能力
```

### 1.2 关键设计决策

| 决策 | 说明 |
|------|------|
| **Hermes 作为默认 Agent 核心** | dedicated / shared runtime 默认走 Hermes Agent 容器；OpenClaw backend 作为显式 fallback 保留 |
| **OpenClaw-compatible API 适配层** | 对外继续保留 `/api/openclaw/*`、`/api/shared-openclaw/*`，底层由 runtime backend selector 分流 |
| **API Key 不进容器** | 所有 LLM API Key 只存在于 Gateway 环境变量中，容器通过 Token 代理访问 |
| **Dedicated 容器级隔离** | dedicated 用户独立容器、独立 Volume，互不干扰 |
| **Shared 逻辑隔离** | shared 用户共用 runtime；平台按 agent/session/workspace 前缀隔离，并记录 run ownership 防止跨用户读取 run 结果或事件 |
| **按需创建** | 用户首次聊天时才创建容器，空闲 30 分钟暂停，30 天归档 |

---

## 2. 多租户部署（Docker Compose）

### 2.1 架构

```
浏览器 --> frontend:3080 --(JS请求)--> gateway(platform):8080 --> 用户容器(hermes)
                                            |                   |
                                       postgres:5432      gateway/llm/v1
                                       (用户/配额)         (注入API Key)
                                                               |
                                                         实际 LLM 提供商
```

- **Frontend**：Vite + React Web 界面，用户注册、登录、聊天
- **Gateway**：平台网关（Python FastAPI），负责认证、用户容器管理、LLM 代理、配额控制
- **用户容器**：每个用户一个独立的 Hermes 实例，自动创建，数据隔离
- **PostgreSQL**：存储用户账户、容器元数据、用量记录

### 2.2 前置条件

- Docker & Docker Compose
- 至少一个 LLM 提供商的 API Key

### 2.3 配置 `.env` 文件

在项目根目录创建 `.env` 文件，填入你的 API Key 和配置：

```bash
# .env — docker compose 自动读取此文件

# ========== 必填：至少配置一个 LLM 提供商 ==========

# 阿里 DashScope（通义千问系列）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx

# Anthropic（Claude 系列）
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx

# OpenAI（GPT 系列）
OPENAI_API_KEY=sk-xxxxxxxxxxxx

# DeepSeek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx

# OpenRouter（支持路由到任意模型，作为兜底）
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxx

# AiHubMix
AIHUBMIX_API_KEY=sk-xxxxxxxxxxxx

# Evolink（OpenAI 兼容聚合代理，支持 GPT-5 / DeepSeek / Gemini 等）
EVOLINK_API_KEY=sk-xxxxxxxxxxxx

# ========== 可选配置 ==========

# 默认模型（新用户容器使用此模型）
DEFAULT_MODEL=dashscope/qwen3-coder-plus

# 平台代理模型输入能力（要支持图片识别请保留 text,image）
# 可选：text 或 text,image
NANOBOT_PROXY__MODEL_INPUT=text,image

# JWT 密钥（生产环境务必修改）
JWT_SECRET=your-secure-random-string
```

### 2.4 支持的模型

配置对应的 API Key 后，用户可以使用以下模型：

| 提供商 | 模型示例 | `.env` 变量 |
|--------|---------|-------------|
| DashScope | `dashscope/qwen3-coder-plus`, `dashscope/qwen-turbo` | `DASHSCOPE_API_KEY` |
| Anthropic | `claude-sonnet-4-5`, `claude-opus-4-5` | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o`, `gpt-4o-mini`, `o3-mini` | `OPENAI_API_KEY` |
| DeepSeek | `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner` | `DEEPSEEK_API_KEY` |
| MiniMax | `minimax/MiniMax-M2.7`, `minimax/MiniMax-M2.7-highspeed` | `MINIMAX_API_KEY` |
| AiHubMix | `aihubmix/模型名` | `AIHUBMIX_API_KEY` |
| Evolink | `evolink/gpt-5.2`, `evolink/deepseek-chat` | `EVOLINK_API_KEY` |
| OpenRouter | `openrouter/任意模型`（兜底） | `OPENROUTER_API_KEY` |

Gateway 根据模型名自动匹配提供商并注入对应的 API Key，用户容器内不存储任何密钥。
MiniMax 默认将 `MiniMax-M2.7` 路由到同族 highspeed 变体以降低回答等待时间；
需要严格使用原始模型时设置 `MINIMAX_M27_USE_HIGHSPEED=false`。

### 2.5 构建与启动

**方式1：一键部署脚本**

```bash
# 准备环境（检查 Docker、下载镜像等）
python prepare.py

# === Docker 部署（推荐） ===

# 本地 Docker 部署（localhost 访问）,推荐python 3.10以上版本
bash build_base_image.sh  #基础镜像先构建，构建hermes镜像，以后修改hermes下的内容，都以直接使用python deploy_docker.py进行基于基础镜像进行build就可以了,可以大大节约build的时间，每次build大概只需要1-2分钟。
build_base_image.sh构建的是hermes-base:lastest
python deploy_docker.py --rebuild hermes 
它构建的是hermes_agent:latest

# 重新构建指定服务（Hermes 是默认底层 runtime 镜像）
python deploy_docker.py --rebuild hermes,gateway,frontend --fast

# 默认 Hermes 镜像跳过 Chromium 预装，并禁用浏览器相关 npm 安装脚本以加快构建；需要 browser 工具时显式打开
python deploy_docker.py --rebuild hermes --with-browser
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright python deploy_docker.py --rebuild hermes --with-browser

# 默认也跳过 WhatsApp bridge 的 GitHub npm 依赖；需要时显式打开
HERMES_INSTALL_WHATSAPP_BRIDGE=true python deploy_docker.py --rebuild hermes

# 仅重建某个服务
python deploy_docker.py --rebuild frontend

# 完全清理重建
python deploy_docker.py --clean
```

# === 本地开发模式 ===

# legacy 本地开发 helper（Docker 部署默认走 Hermes）
python start_local.py

# 仅启动部分服务
python start_local.py --only db,gateway,frontend

# 测试打包 Hermes dedicated runtime
docker build -f hermes-agent/Dockerfile.bridge -t nanobot-hermes-agent:latest hermes-agent/

# 检查服务状态
python check_status.py
```

> **提示**：换网不需要重新 build 前端。前端使用相对路径 `/api/...`，由 nginx 反代转发，与 IP 无关。

本地测试启动后：

```
本地开发环境已启动
        PostgreSQL  http://127.0.0.1:5432  (Docker 容器)
  Hermes Agent      http://127.0.0.1:18080  (PID xxxxx)
  Platform Gateway  http://127.0.0.1:8080
      Frontend Dev  http://127.0.0.1:3080
```

### 2.6 使用

1. 打开浏览器访问 `http://localhost:3080`
2. 注册账号并登录
3. 开始聊天 — Gateway 会自动为你创建隔离的 Hermes 容器

### 2.7 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Frontend | 3080 (映射 3000) | Web 界面 |
| Gateway | 8080 | API 网关（浏览器直接请求） |
| PostgreSQL | 15432 (映射 5432) | 内部数据库 |
| Hermes Runtime (dedicated 容器内) | 18080 | 容器对外 HTTP + SSE |
| Hermes Runtime (shared 容器内) | 8080 | shared runtime API |

### 2.8 数据持久化

| 数据 | 存储方式 |
|------|---------|
| 用户账户、配额、容器元数据 | PostgreSQL（`pgdata` volume） |
| 用户工作区和会话 | Docker named volumes + `/data/hermes-users` |

### 2.9 常用运维命令

```bash
# 查看所有容器
docker ps -a --filter "name=hermes"

# 查看某个用户容器的日志
docker logs -f hermes-user-xxxxxxxx

# 重建 gateway（修改后端代码后）
docker compose build --no-cache gateway && docker compose up -d

# 重建 frontend（修改前端代码或 API 地址后）
docker compose build --no-cache frontend && docker compose up -d

# 完全重置（删除所有数据）
docker compose down -v
docker rm -f $(docker ps -a --filter "name=hermes-user-" -q) 2>/dev/null
```

---

## 4. 整体架构

```
                        ┌──────────────────────┐
                        │   浏览器 (Frontend)    │
                        │   Vite+React :3080        │
                        └──────────┬───────────┘
                                   │ HTTP + WebSocket
                                   v
                        ┌──────────────────────┐
                        │  Platform Gateway     │
                        │  FastAPI :8080         │
                        │  ┌────────────────┐   │
                        │  │ Auth (JWT)      │   │
                        │  │ Container Mgr   │   │
                        │  │ LLM Proxy       │   │
                        │  │ Quota Control   │   │
                        │  └────────────────┘   │
                        └───┬──────────┬───────┘
                            │          │
                  ┌─────────┘          └──────────┐
                  v                               v
        ┌──────────────┐               ┌──────────────────┐
        │  PostgreSQL   │               │  用户容器 (N个)    │
        │  :5432        │               │  ┌──────────────┐ │
        │  用户/配额/    │               │  │ Bridge :18080│ │
        │  容器元数据    │               │  │  HTTP + WS   │ │
        └──────────────┘               │  └──────┬───────┘ │
                                       │         v         │
                                       │  ┌──────────────┐ │
                                       │  │ Hermes Agent │ │
                                       │  │ :18080       │ │
                                       │  │              │ │
                                       │  │ Agent Engine │ │
                                       │  │ Tools/Skills │ │
                                       │  │ Sessions     │ │
                                       │  └──────────────┘ │
                                       └──────────────────┘
                                               │
                                    LLM 请求通过 Gateway 代理
                                               │
                                               v
                                    ┌──────────────────┐
                                    │  LLM Providers    │
                                    │  Anthropic/OpenAI │
                                    │  DashScope/...    │
                                    └──────────────────┘
```

---

## 5. 核心组件详解

### 5.1 Hermes Agent 引擎 (`hermes-agent/`)

Hermes 是一个高性能的 AI Agent 框架（Python），核心能力包括：

- **Agent Loop**：ReAct 模式的工具调用循环，支持多轮迭代
- **工具系统**：Bash 执行、文件读写、Web 搜索/抓取、消息发送等
- **Skills 系统**：Markdown 格式的技能文件，支持内置 + 用户自定义
- **Session 管理**：对话历史持久化
- **多 Provider 支持**：通过 OpenAI 兼容接口对接各种 LLM

### 5.2 Hermes Runtime

Hermes 容器内运行 API 服务，在每个用户容器内运行：

| 组件 | 职责 |
|------|------|
| Hermes API Server | HTTP + SSE API 服务（端口 18080），处理 sessions、runs、skills 等请求 |
| Agent Engine | 工具调用、Skills 执行、对话管理 |
| Workspace | 文件系统操作、代码执行 |

**容器启动流程：**

```
1. 读取环境变量（代理URL、Token、模型名）
2. 写入 Hermes 配置
3. 启动 Hermes API Server（0.0.0.0:18080）
4. 对外暴露 HTTP + SSE API
```

### 5.3 Platform Gateway (`platform/`)

Python FastAPI 应用，是整个平台的控制中心：

| 模块 | 文件 | 职责 |
|------|------|------|
| 认证 | `app/auth/service.py` | JWT + bcrypt，注册/登录/刷新 Token |
| 容器管理 | `app/container/manager.py` | Docker API 创建/暂停/归档/销毁用户容器 |
| LLM 代理 | `app/llm_proxy/service.py` | API Key 注入、配额检查、用量记录 |
| HTTP 代理 | `app/routes/proxy.py` | 转发 HTTP/WebSocket 请求到用户容器 |
| 数据库 | `app/db/models.py` | 用户、容器、用量 ORM 模型 |

**容器生命周期：**

```
用户首次聊天 → create_container()
  ├─ 在 DB 中占位（防并发）
  ├─ 创建 Docker Volume（workspace + sessions）
  ├─ 启动容器（资源限制：2GB RAM, 4 CPU）
  └─ 记录容器 IP、Token

空闲 30 分钟 → pause（暂停容器，释放 CPU）
再次访问    → unpause（秒级恢复）
空闲 30 天  → archive（归档）
用户删除    → destroy（移除容器，保留数据 Volume）
```

### 5.4 LLM 代理机制

容器内的 Hermes 调用 LLM 时，不直接访问 LLM API，而是请求 Gateway 代理：

```
容器内 Hermes
  → POST http://gateway:8080/llm/v1/chat/completions
    Authorization: Bearer <container-token>
    Body: { model: "claude-sonnet-4-5", messages: [...] }

Gateway 处理：
  1. 通过 container-token 查找用户
  2. 检查每日 Token 配额（free: 100K, basic: 1M, pro: 10M）
  3. 根据模型名匹配 Provider（claude→Anthropic, gpt→OpenAI, qwen→DashScope...）
  4. 注入对应的真实 API Key
  5. 调用 LLM，流式/非流式返回结果
  6. 记录 Token 用量
```

### 5.5 Skills 系统

技能文件位于 `hermes-agent/skills/`，每个技能是一个包含 `SKILL.md` 的目录。用户也可以在自己的工作区中创建自定义技能。

**管理接口（通过 Hermes API）：**

- `GET /api/skills` — 列出所有技能（内置 + 用户自定义）
- `POST /api/skills/upload` — 上传技能（ZIP 格式）
- `DELETE /api/skills/:name` — 删除用户自定义技能
- `GET /api/skills/:name/download` — 导出技能

---

## 6. 安全设计

| 层面 | 措施 |
|------|------|
| API Key 隔离 | 所有 LLM API Key 仅存在于 Gateway 环境变量中，用户容器内无任何密钥 |
| 容器隔离 | 每个用户独立 Docker 容器，独立 Volume，资源限制 |
| 认证链路 | 前端 JWT → Gateway → 容器 Token（一次性，仅标识容器身份） |
| 网络隔离 | 用户容器运行在内部网络，通过 Gateway 代理访问 LLM |
| 配额控制 | 每日 Token 配额，按用户等级分层 |
| 容器内安全 | Hermes API Server 仅监听容器内部端口，通过平台 Gateway 代理访问 |

---

## 7. 前端

Vite + React Router 单页应用，暗色主题，位于 `frontend/` 目录。

### 7.1 技术栈

| 技术 | 用途 |
|------|------|
| Vite | 构建工具 |
| React + React Router | 路由与 SPA 框架 |
| Tailwind CSS | 样式 |
| react-markdown + remark-gfm | Markdown 渲染（支持代码高亮、表格、复制按钮） |
| lucide-react | 图标 |

### 目录结构

```
frontend/
├── Dockerfile                  # 生产镜像（npm build → nginx 静态服务）
├── nginx.conf                  # nginx 配置：/ 静态文件，/api → gateway 反代
├── package.json                # 依赖管理
├── vite.config.ts              # Vite 配置（开发代理 /api → localhost:8080）
├── tailwind.config.js          # Tailwind 主题配色
├── index.html                  # SPA 入口 HTML
└── src/
    ├── main.tsx                # React 入口，挂载 <App />
    ├── App.tsx                 # 路由定义（React Router）
    ├── index.css               # 全局样式 + Tailwind @import
    ├── lib/
    │   └── api.ts              # API 客户端（fetch + WebSocket，相对路径 /api/...）
    ├── store/
    │   └── agents.ts           # Agent 数据请求（fetchAgents、fetchDashboardStats 等）
    ├── types/
    │   └── agent.ts            # TypeScript 类型定义（BackendAgent、DashboardStats 等）
    ├── components/
    │   ├── Layout.tsx           # 全局布局：Sidebar + TopBar + <Outlet />
    │   ├── Sidebar.tsx          # 左侧导航栏（仪表盘、Agents、会话、技能…）
    │   ├── TopBar.tsx           # 顶部栏（用户信息、退出登录）
    │   └── MarkdownContent.tsx  # Markdown 渲染组件（代码块 + 复制按钮）
    └── pages/
        ├── Dashboard.tsx        # 仪表盘：统计卡片 + Agent 列表概览
        ├── Login.tsx            # 登录页
        ├── Agents.tsx           # Agent 列表页
        ├── AgentCreate.tsx      # 创建 Agent
        ├── AgentDetail.tsx      # Agent 详情（配置、身份编辑）
        ├── Chat.tsx             # 聊天页：会话列表 + 消息区 + WebSocket + 斜杠命令自动补全
        ├── Sessions.tsx         # 会话管理
        ├── SkillStore.tsx       # 技能商店（搜索、安装、启用/禁用）
        ├── CronJobs.tsx         # 定时任务管理
        ├── KnowledgeBase.tsx    # 知识库文件管理
        ├── FileManager.tsx      # 工作空间文件浏览
        ├── Channels.tsx         # 渠道配置
        ├── AIModels.tsx         # AI 模型管理
        ├── Plugins.tsx          # 插件管理
        ├── Nodes.tsx            # 节点管理
        ├── ApiAccess.tsx        # API Token 管理
        ├── AuditLog.tsx         # 审计日志
        └── SystemSettings.tsx   # 系统设置
```

### 7.3 页面路由

| 路由 | 页面文件 | 功能 |
|------|---------|------|
| `/` | `Dashboard.tsx` | 仪表盘：Agent/会话/技能统计 + Agent 列表概览 |
| `/login` | `Login.tsx` | 用户登录 |
| `/agents` | `Agents.tsx` | Agent 列表 |
| `/agents/new` | `AgentCreate.tsx` | 创建 Agent |
| `/agents/:id` | `AgentDetail.tsx` | Agent 详情与配置 |
| `/agents/:id/chat` | `Chat.tsx` | 与 Agent 对话（WebSocket 实时通信 + Markdown 渲染） |
| `/sessions` | `Sessions.tsx` | 会话管理 |
| `/skills` | `SkillStore.tsx` | 技能商店 |
| `/cron` | `CronJobs.tsx` | 定时任务 |
| `/knowledge` | `KnowledgeBase.tsx` | 知识库 |
| `/files` | `FileManager.tsx` | 文件管理 |
| `/channels` | `Channels.tsx` | 渠道配置 |
| `/models` | `AIModels.tsx` | 模型管理 |
| `/plugins` | `Plugins.tsx` | 插件管理 |
| `/api-access` | `ApiAccess.tsx` | API Token |
| `/audit` | `AuditLog.tsx` | 审计日志 |
| `/settings` | `SystemSettings.tsx` | 系统设置 |

### 7.4 网络请求

- **生产环境**：前端通过 nginx 反代 `/api/*` 到 gateway 容器，无需硬编码 IP
- **开发环境**：Vite 代理 `/api/*` 到 `http://localhost:8080`
- **换网不需要重新 build**：前端使用相对路径 `/api/...`，由反代负责转发

### 7.5 WebSocket 协议

**前端 → Gateway → Hermes Agent**（逐层代理）

```json
// 发送消息
{ "type": "req", "id": 1, "method": "chat.send", "params": { "sessionKey": "...", "message": "..." } }

// 接收回复 (事件推送)
{ "type": "event", "event": "chat.message.received", "payload": { "content": "..." } }

// 心跳
{ "type": "ping" } / { "type": "pong" }
```

---

## 8. deploy_copy — 预置 Agent 与技能

### 8.1 目录结构

```
deploy_copy/
├── hermes_defaults.json                # Hermes 默认配置
├── Agents/                             # 预置 Agent 工作空间
│   ├── hr/                             # 人力资源顾问
│   │   ├── SOUL.md                     # Agent 人格与核心原则
│   │   ├── AGENTS.md                   # Agent 行为规范与工具指南
│   │   └── USER.md                     # 用户画像与交互偏好
│   ├── researcher/                     # 资深研究员
│   │   ├── SOUL.md
│   │   ├── AGENTS.md
│   │   └── USER.md
│   └── programmer/                     # 全栈工程师
│       ├── SOUL.md
│       ├── AGENTS.md
│       └── USER.md
```

### 工作原理

deploy_copy 是一个**部署模板目录**，在启动时自动将预置的 Agent 和技能同步到 Hermes 运行目录。

**同步流程（幂等，只拷贝不存在的文件）：**

```
deploy_copy/Agents/hr/          →  Hermes Agent 工作空间
                                    Agent 注册目录
                                    注册到配置文件

deploy_copy/hermes_defaults.json   →  合并到 Hermes 配置（只添加缺失的 key）
```

**两种部署方式下的实现：**

| 部署方式 | 实现文件 | 同步时机 |
|---------|---------|---------|
| `start_local.py` | `start_local.py` → `_sync_agents()` + `_sync_dir()` | Python 脚本启动时，直接操作本机文件系统 |
| `deploy_docker.py` | 容器 entrypoint | 容器启动时，entrypoint 脚本从 `/deploy-copy/` 同步到 Hermes 目录 |

**Agent 注册的关键步骤：**

1. **创建 Agent 目录** — Hermes 通过扫描 Agent 目录发现 Agent
2. **同步工作空间** — 存放 SOUL.md、AGENTS.md 等文件
3. **写入配置** — 配置文件中添加 Agent 信息（API 返回 Agent 列表的数据源）

> 如果只做了第 2 步但缺少第 1、3 步，Agent 不会在 Web UI 中显示。三步缺一不可。

### 如何添加新的预置 Agent

```bash
# 1. 创建目录
mkdir -p deploy_copy/Agents/my_agent

# 2. 编写 Markdown 配置文件
# SOUL.md — 定义 Agent 的身份、人格、核心原则
# AGENTS.md — 定义行为规范、工具使用指南、输出格式
# USER.md — 定义目标用户画像、交互偏好

# 3. 重新部署
python deploy_docker.py --host localhost        # Docker 方式
# 或
python start_local.py                           # 本地方式（会自动同步）
```

部署后访问 `http://localhost:3080/agents` 即可看到新 Agent。

---

## 📂 文件索引

### 项目根目录

```
项目根目录/
├── .env                            # API Key 配置（不提交到 git）
├── .env.example                    # 环境变量模板
├── docker-compose.yml              # 多租户部署编排（postgres + gateway + frontend）
├── docker-compose.yml.prod         # 生产环境 compose 配置
├── deploy_docker.py                # Docker 一键部署脚本（支持本地/远程/重建/清理）
├── start_local.py                  # 本地开发启动脚本（全服务一键启动）
├── prepare.py                      # 环境准备脚本（检查 Docker、拉镜像）
├── check_status.py                 # 服务状态检查
├── call_agent_api.py               # API 调用示例脚本
├── inspect_db.py                   # 数据库检查工具
├── pyproject.toml                  # Python 项目配置
│
├── deploy_copy/                    # 部署模板（自动拷贝到用户容器）
│   ├── hermes_defaults.json        # Hermes 默认配置
│   ├── Agents/                     # 预置 Agent 工作空间模板
│   │   ├── hr/                     # HR 助手（SOUL.md + AGENTS.md + USER.md）
│   │   ├── researcher/             # 研究员助手
│   │   └── programmer/             # 程序员助手
│
├── hermes-agent/                   # Hermes Agent 引擎
├── platform/                       # 多租户平台网关（FastAPI）
├── frontend/                       # Web 前端（Vite + React）
├── doc/                            # 文档和截图
└── ssh_key/                        # SSH 密钥（远程部署用）
```

### Hermes Agent (`hermes-agent/`)

Hermes 是项目默认的 AI Agent 引擎，每个用户容器内运行。

```
hermes-agent/
├── Dockerfile                      # Hermes 基础镜像
├── Dockerfile.bridge               # Hermes runtime 镜像
├── entrypoint.sh                   # 容器入口脚本
├── pyproject.toml                  # Python 依赖
│
└── src/                            # Hermes 源码
    ├── server.py                   # HTTP + SSE API 服务器（端口 18080）
    ├── agent/                      # Agent 引擎：工具调用、Skills 执行
    ├── routes/                     # REST API 路由
    │   ├── agents.py               # Agent 管理：列表、详情、创建、删除
    │   ├── sessions.py             # 会话管理：列表、历史消息、创建、删除
    │   ├── skills.py               # 技能管理：列表、上传、删除、导出
    │   ├── cron.py                 # 定时任务：创建、删除、启用/禁用
    │   ├── channels.py             # 渠道管理
    │   ├── files.py                # 文件操作：上传、下载
    │   └── marketplaces.py         # 技能市场：搜索和安装 skills.sh 上的技能
```

### Platform 多租户网关 (`platform/`)

Python FastAPI 应用，是整个平台的控制中心。

```
platform/
├── Dockerfile                      # Gateway 镜像（Python 3.11 + uvicorn）
├── pyproject.toml                  # Python 依赖（fastapi, sqlalchemy, docker, jose...）
├── alembic.ini                     # 数据库迁移配置
├── README.md                       # Platform 说明文档
│
├── alembic/                        # 数据库迁移脚本
│   ├── env.py                      # Alembic 环境配置
│   └── script.py.mako              # 迁移脚本模板
│
└── app/                            # FastAPI 应用
    ├── __init__.py
    ├── main.py                     # 应用入口：创建 FastAPI app、挂载路由、启动事件
    ├── config.py                   # 配置中心：API Key、数据库 URL、配额等级、默认模型
    ├── logging_setup.py            # 日志配置
    │
    ├── auth/                       # 认证模块
    │   ├── __init__.py
    │   ├── service.py              # JWT + bcrypt 认证服务（注册/登录/刷新 Token）
    │   └── dependencies.py         # FastAPI 依赖注入（get_current_user 等）
    │
    ├── container/                  # 容器管理模块
    │   ├── __init__.py
    │   └── manager.py              # Docker API 封装：创建/暂停/恢复/归档/销毁用户容器
    │
    ├── db/                         # 数据库模块
    │   ├── __init__.py
    │   ├── engine.py               # SQLAlchemy 异步引擎 + 会话工厂
    │   └── models.py               # ORM 模型：User、Container、Usage
    │
    ├── llm_proxy/                  # LLM 代理模块
    │   ├── __init__.py
    │   └── service.py              # API Key 注入、Provider 匹配、配额检查、用量记录
    │
    └── routes/                     # API 路由
        ├── __init__.py
        ├── auth.py                 # POST /auth/register, /auth/login, /auth/refresh
        ├── proxy.py                # /api/* → 用户容器（HTTP 反代 + WebSocket 代理）
        ├── llm.py                  # POST /llm/v1/chat/completions（容器调 LLM 的入口）
        └── admin.py                # 管理接口：用户列表、容器管理、系统状态
```

### 前端 (`frontend/`)

详见 [前端](#前端) 章节的目录结构。

---

## 🔌 API 调用示例

通过 `call_agent_api.py` 脚本可以从命令行调用 Agent，适合外部系统集成。

```bash
# 使用 API Token（从前端 系统→API 页面生成）
python call_agent_api.py --api-token "eyJ..." --agent main --message "你好"

# 指定 Agent ID
python call_agent_api.py --api-token "eyJ..." --agent insurance --message "帮我分析一下保险方案"

# 复用已有会话
python call_agent_api.py --api-token "eyJ..." --agent main --message "继续" --session "agent:main:session-123"

# 使用用户名密码认证（不推荐）
python call_agent_api.py --username admin --password admin123 --agent main --message "你好"

# 指定服务器地址
python call_agent_api.py --base-url http://192.168.1.100:8080 --api-token "eyJ..." --agent main --message "hello"
```

---

## ⬆️ 升级 Hermes

### 重新构建 Hermes 镜像

```bash
# 重新构建 Hermes 镜像
python deploy_docker.py --rebuild hermes

# 带浏览器支持
python deploy_docker.py --rebuild hermes --with-browser
```

### 常用运维命令

- **列出容器所有卷** — `docker volume ls`
- **删除某个用户的挂载数据** — `docker volume rm xxx`

---

## 🔌 容器端口映射

### 浏览器端口和服务端口暴露

容器的内部端口 5900（浏览器端口）和 30000（外部端口）会被映射到主机的随机端口上。

```python
browser_binding = _published_binding(docker_container, "5900/tcp")
service_binding = _published_binding(docker_container, "30000/tcp")
```

---

## 🔗 渠道配置

如何配置 Channel，打通 QQ、飞书等：

https://zhuanlan.zhihu.com/p/2016049817437111235

---

## 💡 可选改进建议

### 功能建议

1. 后台前端能否添加自己的模型统计
2. 渠道管理安装完点击删除没有响应
3. 对话框输入超过两行的时候可不可以自动扩充到六七行这种高度
4. 上传的文件名字太长就延长掉了删除按钮的位置，就无法删除
5. 模型回复太多了，比如写文献的时候就会显示被截断，这个机制需不需要修正
6. 思考和做了什么的过程能展示吗或者以折叠的方式，当前只展示结果

### 其他建议

- 支持 Agent 配置备份与分发：管理员统一配置并备份 Agent，可下发给普通用户，防止用户误删/改坏技能，确保功能可用
- 实时终端升级：现在自带的这个实时终端，好像不太好用，能执行一些简单的命令，能否升级一下

---

## 📚 相关文档

- 如何配置 nginx 进行域名设置：`doc/hermes_web.conf`
- 数据库表结构：`doc/table.md`
- 离线部署文档：`doc/离线部署.md`
- vLLM 支持文档：`doc/vllm.md`
- 更改 Logo 和名称：`doc/更改Logo和名称.md`

---

## 📬 联系方式

如有问题，请联系作者：**johnsongzc**

![weichat.png](doc/weichat.png)

---

## 📄 许可证

详见 [LICENSE](LICENSE) 文件。
