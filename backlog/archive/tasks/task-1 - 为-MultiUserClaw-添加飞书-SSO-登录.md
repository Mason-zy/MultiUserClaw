---
id: TASK-1
title: 为 MultiUserClaw 添加飞书 SSO 登录
status: 'Basic: Done'
assignee: []
created_date: '2026-06-26 06:50'
updated_date: '2026-06-26 08:52'
labels:
  - 'kind:basic'
dependencies: []
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
为 MultiUserClaw 添加飞书 SSO 登录，复用 agentgateway (/home/fjd/Project/agentgateway/auth-service/) 已实现的飞书 OAuth。扩展现有 platform/app/auth/（已有 bcrypt + jose JWT + user CRUD），飞书登录成功后复用 create_access_token 发 JWT。凭证从 .env 读，禁止硬编码/进 git。需迁移 agentgateway auth-service/tests/test_feishu_routes.py 保证 OAuth 流程测试覆盖。FastAPI + lark-oapi 已在依赖。
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
# Proposal: 为 MultiUserClaw 添加飞书 SSO 登录

## Background

MultiUserClaw 平台目前仅支持用户名/密码注册与登录（`platform/app/routes/auth.py` 的 `/api/auth/register`、`/api/auth/login`）。这种账号体系在企业内部团队场景下有三个痛点：管理员要手工开通账号、密码要单独记忆与轮换、无法与现有企业身份目录打通。虽然 `auth/service.py` 已预留了 `sso_uid`/`sso_token` 字段和 `create_or_update_sso_user` 函数，但它是 InfoX-Med 专用骨架，没有接入任何路由、也非飞书。同一代码组织内的 agentgateway 项目已经实现并验证了一套飞书 OAuth（`auth-service/routes/feishu.py` + `services/feishu_client.py`，授权码 → user_access_token → 用户信息 + 部门），并在生产中用于身份认证。复用这套已验证的飞书 OAuth 模式，给 MultiUserClaw 增加飞书扫码/授权登录，可以让团队成员用既有飞书账号一键登录，消除手工开号成本并天然继承企业组织架构（部门/职位）。

## Goals

1. 新增平台配置位，支持通过环境变量提供飞书应用凭证：`PLATFORM_FEISHU_APP_ID`、`PLATFORM_FEISHU_APP_SECRET`、`PLATFORM_FEISHU_BASE_URL`（默认 `https://open.feishu.cn/open-apis`）、`PLATFORM_FEISHU_CALLBACK_URL`、`PLATFORM_FEISHU_FRONTEND_REDIRECT_URL`。可通过 `grep -n "feishu" platform/app/config.py` 验证字段存在。
2. 新增 `platform/app/services/feishu_client.py`，移植 agentgateway 的飞书 API 客户端（`get_app_access_token`、`code_to_user_access_token`、`get_user_info`、`get_user_department`、`get_full_user_info`）。可通过 `ls platform/app/services/feishu_client.py` 验证文件存在。
3. 新增带 CSRF 防护的 OAuth 状态存储 `platform/app/services/oauth_state.py`（一次性随机 state，TTL 600 秒，消费即失效），复刻 agentgateway `services/login_state.py` 的 `create_state`/`consume_state_record` 语义。可通过 `ls platform/app/services/oauth_state.py` 验证。
4. 新增 `GET /api/auth/feishu/login` 端点，返回 302 重定向到飞书授权页（携带 `app_id`、`redirect_uri`、`response_type=code`、随机 `state`）。可通过 `curl -i http://<host>/api/auth/feishu/login` 看到 302 与 `Location: https://open.feishu.cn/open-apis/authen/v1/authorize?...` 验证。
5. 新增 `GET /api/auth/feishu/callback` 端点，接收授权码与 state，校验 state、用授权码换取飞书用户信息（open_id/name/email/department），在 `users` 表中按 `sso_uid=feishu_open_id` 查找或创建用户（复用并改造现有 `get_user_by_sso_uid`/`create_or_update_sso_user` 为通用 SSO 路径），随后调用现有 `create_access_token`/`create_refresh_token` 签发平台自有 HS256 JWT，并 302 重定向回前端（token 放 query）。可通过 `curl -i "http://<host>/api/auth/feishu/callback?code=...&state=..."` 验证其 302 行为与错误分支（缺/过期 state 返回错误重定向）。
6. 新增 `POST /api/auth/feishu/token` 端点（API 模式，授权码直接换 token，不重定向，返回 `TokenResponse`），覆盖非浏览器场景（如飞书机器人内嵌）。可通过向其 POST `code` 验证返回结构与 `/api/auth/login` 一致。
7. 前端登录页（`frontend/src/pages/Login.tsx`）新增「飞书登录」入口，点击后跳转到 `/api/auth/feishu/login`；回调落地的页面消费 query 中的 token 完成登录态。可通过在 `Login.tsx` 中 `grep -n "feishu"` 验证入口存在。
8. 不破坏现有用户名/密码登录、注册、refresh、/me、change-password 等任何既有 `/api/auth/*` 路由（回归 `pytest platform/tests/` 全绿验证）。

## Proposed Approach

**组件分解（平台后端）**：
- `platform/app/services/feishu_client.py`：从 agentgateway `services/feishu_client.py` 移植，保持 `get_full_user_info(code) -> {sub, name, email, department, position, avatar}` 的契约不变。底层仍用平台已有的 `httpx` 调用飞书 OpenAPI（`/auth/v3/app_access_token/internal`、`/authen/v1/oidc/access_token`、`/authen/v1/user_info`、`/contact/v3/users/{id}`、`/contact/v3/departments/{id}`），不引入新的网络库。可选的部门映射兜底文件沿用 agentgateway 的 `department_map.json` 约定。
- `platform/app/services/oauth_state.py`：进程内一次性 state 存储（移植 agentgateway `login_state.py` 的 state 部分），TTL 600 秒，`create_state()` 返回 `secrets.token_urlsafe(32)`，`consume_state_record(state)` 取出即删。本提案范围内 MultiUserClaw 以单实例部署为前提；多实例扩展见 Trade-offs。
- `platform/app/routes/feishu_auth.py`（新路由文件，注册到 `main.py`）：实现 `/login`、`/callback`、`/token` 三个端点，统一挂在 `/api/auth` 前缀下。`/login` 仅构造授权 URL 并 302；`/callback` 完成授权码 → 用户信息 → 本地用户映射 → 签发平台 JWT → 重定向前端；`/token` 同样换用户信息与签发但不重定向，直接返回 `TokenResponse`。

**与现有 auth 的集成（关键设计）**：
- 飞书身份到本地用户的映射走 `users.sso_uid`：`sso_uid` 存飞书 `open_id`（加 `feishu:` 前缀以与未来其他 IdP 区分，如 `feishu:ou_xxx`）。复用现有 `get_user_by_sso_uid`；将 `create_or_update_sso_user` 从 InfoX-Med 专用改造为通用（接收 IdP 标识 + open_id + 显示名 + email），新用户用飞书 name 作 username、飞书 email 作 email，随机密码占位（与现有骨架一致）。这一改造保持函数签名向后兼容（InfoX-Med 调用点目前不存在路由，零回归风险）。
- **签发 token 复用平台现有 HS256 链路**：飞书 JWT 不直接作为平台会话凭证（遵守 agentgateway CLAUDE.md 第 21 行「飞书 JWT 只用于身份认证」）。流程是：飞书 user_access_token 仅在 `feishu_client` 内部用于一次性拉取用户信息，不落库、不作为会话 token；登录成功后调用现有 `create_access_token(user.id, user.role)` / `create_refresh_token(user.id)` 签发平台自有 HS256 JWT，与 `/login` 路由返回的 `TokenResponse` 完全一致。这样 `get_current_user` 依赖（`dependencies.py`）零改动即可同时保护密码登录与飞书登录后的所有下游接口。
- 配置扩展加在 `platform/app/config.py` 的 `Settings` 类中，沿用现有 `env_prefix="PLATFORM_"` 约定（即字段 `feishu_app_id` 对应环境变量 `PLATFORM_FEISHU_APP_ID`）。

**前端**：登录页加一个「飞书登录」按钮，点击 `window.location.href = '/api/auth/feishu/login'`；新增/复用一个回调落地路由（如 `/login/feishu`）读取 query 的 `code`（实为平台 access_token）写入本地存储后跳转 dashboard。本提案不指定具体落地实现细节，留待 plan 阶段。

**测试参考**：agentgateway 的 `tests/test_feishu_routes.py` 提供 OAuth 路由的测试范式（mock 飞书 API、断言重定向与 state 行为），移植到平台测试目录作为骨架。

## Trade-offs and Risks

**不做（scope 外）**：
- 不做飞书工作台/小程序内嵌登录（`/feishu/token` 已覆盖纯 API 场景，足够）。
- 不做多租户 / 多 IdP 抽象层：仅落地飞书一条链路；`sso_uid` 加 IdP 前缀是为未来预留，但本提案不实现 OIDC/SAML 通用框架。
- 不做 agentgateway 的 CLI 登录流（`/feishu/cli-login`、`/feishu/cli/exchange`、key-display）：那是 agentgateway CLI 专用，MultiUserClaw 是 Web 平台，不需要。
- 不做飞书自动开通 API Key / permission-center 联动（agentgateway 的 `_auto_provision_key`）：MultiUserClaw 无此子系统。

**已知风险**：
- **state 存储是进程内内存**（移植自 agentgateway `login_state.py`），仅适合单实例。若 MultiUserClaw 后续多 worker/多实例部署，需替换为 Redis/DB 共享存储——本提案明确以单实例为前提，多实例方案留待 plan 评估。
- **凭证管理**：`FEISHU_APP_SECRET` 通过环境变量注入，轮换需协调飞书开放平台重置 secret 后同步更新部署环境；本提案不实现自动轮换。
- **通讯录 API 权限**：拉取部门依赖飞书应用的通讯录读取权限范围（scope）；权限不足时 `get_user_department` 已兜底返回 `unknown` 并尝试 `department_map.json`，属降级而非阻塞。
- **用户名冲突**：飞书返回的 name 可能重复或为空，需在用户创建时做唯一性兜底（现有骨架已用 `get_user_by_username` 检查并追加后缀，沿用此策略）。
- **HS256 vs RS256**：agentgateway 用非对称 RS256（jwks 可外部验签），MultiUserClaw 平台用对称 HS256。本提案不统一两者——平台 JWT 只服务自身会话，无需跨服务验签，保持 HS256 最简。

**备选方案（已否决）**：
- 直接复用 agentgateway 的 auth-service 作为统一身份网关、MultiUserClaw 只验签其 JWT：否决，因为会引入跨服务依赖与 RS256 密钥分发，且 MultiUserClaw 已有自洽的 HS256 会话体系，收益不抵复杂度。
- 在 MultiUserClaw 内引入 lark-oapi SDK 替代 httpx 调飞书：否决，lark-oapi 目前只在 monorepo hermes-agent 侧使用、平台未引入；agentgateway 已用裸 httpx 验证可行，保持一致更省事。

---

# Plan: 为 MultiUserClaw 添加飞书 SSO 登录

Proposal: /tmp/ftb-muc/ftb-proposal.md（TASK-1 Implementation Plan）

> **实现路径微调（相对 proposal）**：Phase 4 的用户映射改用**新增** `get_or_create_feishu_user` 独立函数，而非 proposal Goal 5 / Approach 所述"改造 `create_or_update_sso_user`"。目的：`service.py` **零侵入**，便于与上游作者 push 合并（详见 Constraints）。Goal 本质（按 sso_uid 查/建用户 + 发 JWT）完全不变。

测试命令统一用 `pytest`，在 `platform/` 目录下执行（conftest.py 已把 `platform/` 注入 `sys.path`，故 `from app.xxx` 可解析）。各 Phase 的 `### Tests (write first)` 描述先写的失败测试；DoD 第一条一律以 `pytest` 开头以证明 red→green。每个 Phase 代码改动 ≤ 200 行。

## Phase 1: 平台配置位（feishu 字段）

### Tests (write first)
- `platform/tests/test_feishu_config.py::test_feishu_app_id_field_exists` — 断言 `Settings()` 实例有 `feishu_app_id` 属性且默认为空串
- `platform/tests/test_feishu_config.py::test_feishu_base_url_default` — 断言 `Settings().feishu_base_url == "https://open.feishu.cn/open-apis"`
- `platform/tests/test_feishu_config.py::test_feishu_env_prefix_mapping` — 用 `monkeypatch.setenv("PLATFORM_FEISHU_APP_ID", "cli_xxx")` 后重建 `Settings()`，断言 `feishu_app_id == "cli_xxx"`（验证 `env_prefix="PLATFORM_"` 生效）

### Implementation
- `platform/app/config.py`: 在 `Settings` 类内新增 5 个字段（沿用 `env_prefix="PLATFORM_"`）：
  - `feishu_app_id: str = ""`
  - `feishu_app_secret: str = ""`
  - `feishu_base_url: str = "https://open.feishu.cn/open-apis"`
  - `feishu_callback_url: str = ""`
  - `feishu_frontend_redirect_url: str = ""`

### DoD
- [ ] `pytest platform/tests/test_feishu_config.py -v`
- [ ] `grep -q "feishu_app_id" platform/app/config.py`
- [ ] `grep -q "feishu_base_url" platform/app/config.py`

## Phase 2: OAuth state 存储（CSRF 防护）

### Tests (write first)
- `platform/tests/test_oauth_state.py::test_create_state_returns_urlsafe_token` — `create_state("web")` 返回非空字符串，且两次调用结果不同
- `platform/tests/test_oauth_state.py::test_consume_state_record_returns_record_and_deletes` — `create_state` 后 `consume_state_record(state)` 返回含 `intent` 的 dict；再次 `consume_state_record` 同一 state 返回 `None`（一次性）
- `platform/tests/test_oauth_state.py::test_consume_unknown_state_returns_none` — `consume_state_record("nope")` 返回 `None`
- `platform/tests/test_oauth_state.py::test_expired_state_returns_none` — monkeypatch `time.time` 让 state 过期 (>600s)，`consume_state_record` 返回 `None`

### Implementation
- 新建 `platform/app/services/__init__.py`（空文件，使其成为 package）
- 新建 `platform/app/services/oauth_state.py`：移植 `/home/fjd/Project/agentgateway/auth-service/services/login_state.py` 的 state 部分，定义：
  - `STATE_TTL_SECONDS = 600`
  - 模块级 `_STATE_STORE: dict[str, dict] = {}`
  - `_cleanup_expired(now=None)` — 清理过期 state
  - `create_state(intent: str, metadata: dict | None = None) -> str` — `secrets.token_urlsafe(32)`，存入 `_STATE_STORE`
  - `consume_state_record(state: str) -> dict | None` — pop 出即删（一次性）
- 不移植 `store_login_token`/`exchange_login_code`（CLI 专用，超出范围）

### DoD
- [ ] `pytest platform/tests/test_oauth_state.py -v`
- [ ] `test -f platform/app/services/oauth_state.py`
- [ ] `grep -q "STATE_TTL_SECONDS" platform/app/services/oauth_state.py`

## Phase 3: 飞书 API 客户端（feishu_client）

### Tests (write first)
- `platform/tests/test_feishu_client.py::test_get_full_user_info_returns_claims` — 用 FakeAsyncClient mock `httpx.AsyncClient`，模拟 app_access_token / oidc access_token / user_info / contact user / contact department 五个端点均 `code==0`，断言 `get_full_user_info("code")` 返回 dict 含 `sub`/`name`/`email`/`department`
- `platform/tests/test_feishu_client.py::test_get_app_access_token_raises_on_error` — mock 返回 `code!=0`，`pytest.raises(Exception)` 断言抛错且消息含「app_access_token」
- `platform/tests/test_feishu_client.py::test_get_user_department_fallback_unknown` — contact API 返回 `code!=0`，断言 `get_user_department` 兜底返回 `"unknown"`
- `platform/tests/test_feishu_client.py::test_uses_settings_for_credentials` — 断言客户端从 `app.config.settings` 读取 `feishu_app_id`/`feishu_app_secret`/`feishu_base_url`（mock settings 验证请求体含对应值），凭证不硬编码

### Implementation
- 新建 `platform/app/services/feishu_client.py`：移植 `/home/fjd/Project/agentgateway/auth-service/services/feishu_client.py`，改动点：
  - 凭证源从 agentgateway 的 `from config import FEISHU_APP_ID...` 改为 `from app.config import settings`，读取 `settings.feishu_app_id` / `settings.feishu_app_secret` / `settings.feishu_base_url`
  - 保留 `get_app_access_token`、`code_to_user_access_token`、`get_user_info`、`get_user_department`、`get_full_user_info` 五个函数，契约不变（`get_full_user_info(code) -> {sub, name, email, department, position, avatar}`）
  - 保留 `_load_dept_map` 兜底（`department_map.json` 约定），`_raise_feishu_api_error` 不泄露敏感字段
  - 底层仍用 `httpx.AsyncClient`，不引入新网络库

### DoD
- [ ] `pytest platform/tests/test_feishu_client.py -v`
- [ ] `grep -q "from app.config import settings" platform/app/services/feishu_client.py`
- [ ] `grep -q "get_full_user_info" platform/app/services/feishu_client.py`

## Phase 4: 飞书用户映射函数（新增，零侵入 service.py）

### Tests (write first)
- `platform/tests/test_feishu_user.py::test_get_or_create_feishu_user_creates_new` — FakeDb（`get_user_by_sso_uid` 返回 None），调 `get_or_create_feishu_user(db, sso_uid="feishu:ou_xxx", display_name="Alice", email="a@b.com")`，断言新建 User 的 `sso_uid == "feishu:ou_xxx"`、`username == "Alice"`、`email == "a@b.com"`、`password_hash` 非空（随机占位）
- `platform/tests/test_feishu_user.py::test_get_or_create_feishu_user_returns_existing` — FakeDb `get_user_by_sso_uid` 先返回已有 user，断言直接返回该 user，不新建
- `platform/tests/test_feishu_user.py::test_get_or_create_feishu_user_username_collision_suffix` — `get_user_by_username` 返回已存在，断言 username 追加后缀保证唯一
- `platform/tests/test_feishu_user.py::test_existing_create_or_update_sso_user_unchanged` — **回归守护**：grep `async def create_or_update_sso_user` 确认原 InfoX-Med 函数签名未变（仍是 `sso_token: str` 必填、无 `email`/`provider` 参数），证明原函数零改动

### Implementation
- **只追加，不改任何已有函数**。在 `platform/app/auth/service.py` **末尾**新增独立函数（复用现有 `get_user_by_sso_uid` / `hash_password` / `get_user_by_username`）：
  ```python
  async def get_or_create_feishu_user(
      db: AsyncSession,
      *,
      sso_uid: str,           # 已带 "feishu:" 前缀
      display_name: str,
      email: str,
  ) -> User:
      """飞书 SSO 专用：按 sso_uid 查/建用户。
      刻意独立于 create_or_update_sso_user（InfoX-Med），零侵入以便与上游合并。
      """
      user = await get_user_by_sso_uid(db, sso_uid)
      if user is not None:
          return user
      username = display_name or sso_uid
      # 沿用现有 get_user_by_username 做唯一性兜底（冲突追加后缀）
      existing = await get_user_by_username(db, username)
      if existing is not None:
          username = f"{username}_{sso_uid[-6:]}"
      user = User(
          sso_uid=sso_uid,
          username=username,
          email=email or f"{sso_uid}@feishu.sso",
          password_hash=hash_password(_random_password()),
      )
      db.add(user)
      await db.flush()
      return user
  ```
  - 顶部 import 区**追加** `import secrets`（如尚无）+ 加 `_random_password()` 小助手（或直接内联 `secrets.token_urlsafe(16)`）。属追加式改动，不修改任何已有行
- **原 `create_or_update_sso_user`（InfoX-Med）完全不动** —— 零回归、零合并冲突

### DoD
- [ ] `pytest platform/tests/test_feishu_user.py -v`
- [ ] `grep -q "get_or_create_feishu_user" platform/app/auth/service.py`
- [ ] `grep -q "async def create_or_update_sso_user" platform/app/auth/service.py`

## Phase 5: 飞书 SSO 路由（/login + /callback + /token）

### Tests (write first)
- `platform/tests/test_feishu_auth_routes.py::test_login_redirects_to_feishu_authorize` — monkeypatch `oauth_state.create_state` 返回固定 state，调 `feishu_login()`，断言 302 且 `Location` 以 `https://open.feishu.cn/open-apis/authen/v1/authorize?` 开头，query 含 `app_id`/`redirect_uri`/`response_type=code`/`state`
- `platform/tests/test_feishu_auth_routes.py::test_callback_missing_state_redirects_with_error` — `feishu_callback(code="c", state=None)`，断言 302 重定向到 `frontend_redirect_url` 且 query 含 error
- `platform/tests/test_feishu_auth_routes.py::test_callback_unknown_state_redirects_with_error` — state 未签发，断言错误重定向
- `platform/tests/test_feishu_auth_routes.py::test_callback_valid_state_creates_user_and_issues_jwt` — monkeypatch `get_full_user_info` 返回固定 claims，用 FakeDb（`get_user_by_sso_uid` 返回 None → 走新建），调 `feishu_callback`，断言 302 重定向到前端且 query 含 `access_token`（非空）
- `platform/tests/test_feishu_auth_routes.py::test_callback_consumed_state_rejected` — 同一 state 第二次调用返回错误重定向（一次性）
- `platform/tests/test_feishu_auth_routes.py::test_token_endpoint_returns_token_response` — monkeypatch `get_full_user_info` + FakeDb，调 `feishu_token(code="c")`，断言返回 `TokenResponse` 结构（含 `access_token`/`refresh_token`/`user_id`/`username`/`role`），与 `/api/auth/login` 一致
- `platform/tests/test_feishu_auth_routes.py::test_token_endpoint_failure_returns_500` — `get_full_user_info` 抛异常，断言 500 且错误体固定文案

### Implementation
- 新建 `platform/app/routes/feishu_auth.py`，定义 `router = APIRouter(prefix="/api/auth", tags=["auth"])`（复用 `/api/auth` 前缀，避免破坏现有路由）：
  - `GET /feishu/login` → 构造授权 URL（`app_id`/`redirect_uri=settings.feishu_callback_url`/`response_type=code`/`state=oauth_state.create_state("web")`）并 302
  - `GET /feishu/callback` → 校验 state（`oauth_state.consume_state_record`，缺失/失效→错误重定向到 `settings.feishu_frontend_redirect_url`）→ `feishu_client.get_full_user_info(code)` → `service.get_or_create_feishu_user(db, sso_uid="feishu:"+claims["sub"], display_name=claims["name"], email=claims["email"])` → `create_access_token(user.id, user.role)` + `create_refresh_token(user.id)` → 302 重定向前端，token 放 query
  - `POST /feishu/token` → 同样换用户信息+签发，但不重定向，直接返回 `TokenResponse`（复用 `platform/app/routes/auth.py` 的 `TokenResponse` schema）
- 从 `platform/app/routes/auth.py` import `TokenResponse`（不重复定义）

### DoD
- [ ] `pytest platform/tests/test_feishu_auth_routes.py -v`
- [ ] `grep -q "feishu/login" platform/app/routes/feishu_auth.py`
- [ ] `grep -q "feishu/callback" platform/app/routes/feishu_auth.py`
- [ ] `grep -q "feishu/token" platform/app/routes/feishu_auth.py`
- [ ] `grep -q "create_access_token" platform/app/routes/feishu_auth.py`

## Phase 6: 路由注册 + 前端登录入口与回调落地页

### Tests (write first)
- `platform/tests/test_feishu_router_registration.py::test_feishu_auth_router_mounted` — import `app.main.app`，遍历 `app.routes`，断言存在路径 `/api/auth/feishu/login`、`/api/auth/feishu/callback`、`/api/auth/feishu/token`
- `platform/tests/test_feishu_router_registration.py::test_existing_auth_routes_preserved` — 断言 `/api/auth/login`、`/api/auth/register`、`/api/auth/refresh`、`/api/auth/me` 仍在 `app.routes`（回归不破坏）
- `platform/tests/test_feishu_router_registration.py::test_feishu_callback_redirect_carries_token` — 用 `httpx.AsyncClient(app=app.main.app)` 对 `/api/auth/feishu/callback` 发请求（monkeypatch `oauth_state.create_state`/`get_full_user_info` + FakeDb），断言 302 Location 的 query 含 `access_token=` 与 `refresh_token=`（证明前端落地页能从 URL 拿到 token，登录链路闭合）

### Implementation
- 改 `platform/app/main.py`：
  - 第 17 行 import 增加 `feishu_auth`：`from app.routes import admin, auth, feishu_auth, llm, models, proxy`
  - 在 `app.include_router(auth.router)` 之后加 `app.include_router(feishu_auth.router)`
- 改 `frontend/src/pages/Login.tsx`：
  - 在登录表单下方（toggle 段落之前）新增「飞书登录」分隔区与按钮，点击触发 `window.location.href = '/api/auth/feishu/login'`
- 新建 `frontend/src/pages/FeishuCallback.tsx`（**回调落地页，消费 query token —— proposal Goal 7**）：
  - 用 `useSearchParams` 读 `access_token` / `refresh_token` / `error`
  - `error` 非空 → 显示登录失败提示 + 返回登录页链接
  - token 非空 → 写入本地存储（复用项目现有 token 存储约定，与 `Login.tsx` 登录成功后一致），调 `navigate('/')` 跳 dashboard
  - token 与 error 都空 → 视为非法访问，跳回 `/login`
- 改 `frontend/src/App.tsx`：在 `<Routes>` 内（`<Route path="/login" ...>` 第 31 行附近）新增 `<Route path="/login/feishu" element={<FeishuCallback />} />`（**不**用 `RequireAuth` 包裹）

### DoD
- [ ] `pytest platform/tests/test_feishu_router_registration.py -v`
- [ ] `grep -q "feishu_auth" platform/app/main.py`
- [ ] `grep -q "feishu" frontend/src/pages/Login.tsx`
- [ ] `test -f frontend/src/pages/FeishuCallback.tsx`
- [ ] `grep -q "useSearchParams" frontend/src/pages/FeishuCallback.tsx`
- [ ] `grep -q '/login/feishu' frontend/src/App.tsx`

## Constraints

- **凭证禁止硬编码**：`feishu_app_id`/`feishu_app_secret` 一律从 `settings` 读取，不得在源码中出现字面量凭证。
- **飞书 user_access_token 不得落库、不得作为会话凭证**：仅在 `feishu_client` 内部一次性拉取用户信息后丢弃；会话凭证一律用平台自有 HS256 JWT（`create_access_token`/`create_refresh_token`），保证 `get_current_user` 依赖零改动即可保护飞书登录后的下游接口。
- **不破坏现有 `/api/auth/*` 路由**：register / login / refresh / me / change-password / api-token 必须保持原语义，回归 `pytest` 全绿。
- **state 存储为进程内内存**（移植自 agentgateway `login_state.py`），仅适合单实例；多实例部署需替换为 Redis/DB——本计划明确以单实例为前提。
- **`sso_uid` 加 IdP 前缀**（`feishu:ou_xxx`）以与未来其他 IdP 区分，但本计划不实现通用 OIDC/SAML 框架。
- **User 表 schema 零迁移**：`sso_uid`/`sso_token` 列已存在（`platform/app/db/models.py` 第 37-38 行），无需新增 alembic 迁移。
- **service.py 零侵入**（便于与上游作者 push 合并）：只**追加** `get_or_create_feishu_user` 独立函数，原 `create_or_update_sso_user`（InfoX-Med 专用）**完全不动**。新函数与原函数逻辑略有重复（~20 行）是有意代价，换取零合并冲突。
- **不移植 agentgateway 的 CLI 流程**（`/feishu/cli-login`、`/feishu/cli/exchange`、key-display、`_auto_provision_key`）：超出 MultiUserClaw Web 平台范围。
- **不引入新网络库**：底层仍用平台已有的 `httpx`，不引入 `lark-oapi` SDK。

## Acceptance Gate
- [ ] `pytest`
- [ ] `pytest platform/tests/ -v`
- [ ] `grep -rn "feishu" platform/app/config.py platform/app/services/feishu_client.py platform/app/services/oauth_state.py platform/app/routes/feishu_auth.py platform/app/main.py frontend/src/pages/Login.tsx`
- [ ] `! grep -rn "FEISHU_APP_SECRET\s*=" platform/app/`
- [ ] `grep -qE '@router\.(post|get)\("/(login|register|refresh|me)"' platform/app/routes/auth.py`
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
claimed: 2026-06-26T08:00:56Z

Phase 1 ✓ 2026-06-26T08:06:03Z — config feishu 字段 (5 fields, env_prefix PLATFORM_). Tests 3/3 green. DoD #1-3 PASS

Phase 2 ✓ 2026-06-26T08:07:06Z — oauth_state (CSRF, TTL 600s, one-time). Tests 4/4 green. DoD #4-6 PASS

Phase 3 ✓ 2026-06-26T08:23:14Z — feishu_client.py (5 funcs, settings creds, app_token reused in get_full_user_info). Tests 4/4 green. DoD #7-9 PASS

Phase 4 ✓ 2026-06-26T08:28:17Z — get_or_create_feishu_user appended to service.py (zero-intrusion, original create_or_update_sso_user untouched). Tests 4/4 green. DoD #38-40 PASS

Phase 5 ✓ 2026-06-26T08:31:33Z — feishu_auth.py router (/login 302, /callback state+JWT+302, /token TokenResponse). Tests 7/7 green. DoD #41-45 PASS

Phase 6 ✓ 2026-06-26T08:47:37Z — main.py registers feishu_auth.router (+2 lines); Login.tsx 飞书按钮; FeishuCallback.tsx (useSearchParams→setTokens→navigate); App.tsx /login/feishu route. Backend tests 3/3 green. DoD #46-51 PASS

Acceptance Gate: feishu 单文件 DoD 全绿 (25/25 tests). 全量 pytest: 113 passed, 32 skipped, 2 FAILED (test_models_config.py — 既有 bug in container/manager.py _build_hermes_env_file lambda, 0 feishu refs, 非本任务代码问题). 注: litellm/docker 缺失已用测试内 stub 兜底 (仅 test_feishu_router_registration.py 本地 import guard，不影响功能).

Completed: 2026-06-26T08:52:16Z — merged to main (2844fee18). 飞书 SSO 测试 25/25 绿。全量 pytest 2 失败为 pre-existing (test_models_config/container/manager.py，非本任务)。
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-06-26 06:57
---
Proposal self-review: APPROVED (Motivation/Goals/Feasibility/Completeness/Consistency 全部通过)
---

created: 2026-06-26 07:02
---
Plan drafted. TDD phases ready for review loop.
---

created: 2026-06-26 07:14
---
Plan review iter 1: NEEDS_REVISION (3 FAIL: Goal7 落地页未覆盖 / Acceptance grep 假失败 / Phase4 签名未锁)。已修订 plan v2，进入 iter 2。
---

created: 2026-06-26 07:16
---
Plan review iter 2: APPROVED (9 项全过 + 3 FAIL 已修复)
---

created: 2026-06-26 07:51
---
Plan v3: Phase4 改零侵入（新增 get_or_create_feishu_user，原 create_or_update_sso_user 不动），便于上游合并。进入 iter 3 review。
---

created: 2026-06-26 07:53
---
Plan review iter 3: APPROVED (v3 零侵入修订通过，9 项全过)
---
<!-- COMMENTS:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 pytest platform/tests/test_feishu_config.py -v
- [ ] #2 grep -q "feishu_app_id" platform/app/config.py
- [ ] #3 grep -q "feishu_base_url" platform/app/config.py
- [ ] #4 pytest platform/tests/test_oauth_state.py -v
- [ ] #5 test -f platform/app/services/oauth_state.py
- [ ] #6 grep -q "STATE_TTL_SECONDS" platform/app/services/oauth_state.py
- [ ] #7 pytest platform/tests/test_feishu_client.py -v
- [ ] #8 grep -q "from app.config import settings" platform/app/services/feishu_client.py
- [ ] #9 grep -q "get_full_user_info" platform/app/services/feishu_client.py
- [ ] #10 pytest platform/tests/test_sso_user.py -v
- [ ] #11 grep -q "provider" platform/app/auth/service.py
- [ ] #12 grep -q "feishu" platform/app/auth/service.py
- [ ] #13 pytest platform/tests/test_feishu_auth_routes.py -v
- [ ] #14 grep -q "feishu/login" platform/app/routes/feishu_auth.py
- [ ] #15 grep -q "feishu/callback" platform/app/routes/feishu_auth.py
- [ ] #16 grep -q "feishu/token" platform/app/routes/feishu_auth.py
- [ ] #17 grep -q "create_access_token" platform/app/routes/feishu_auth.py
- [ ] #18 pytest platform/tests/test_feishu_router_registration.py -v
- [ ] #19 grep -q "feishu_auth" platform/app/main.py
- [ ] #20 grep -q "feishu" frontend/src/pages/Login.tsx
- [ ] #21 test -f frontend/src/pages/FeishuCallback.tsx
- [ ] #22 grep -q "useSearchParams" frontend/src/pages/FeishuCallback.tsx
- [ ] #23 grep -q '/login/feishu' frontend/src/App.tsx
- [ ] #24 pytest
- [ ] #25 pytest platform/tests/ -v
- [ ] #26 grep -rn "feishu" platform/app/config.py platform/app/services/feishu_client.py platform/app/services/oauth_state.py platform/app/routes/feishu_auth.py platform/app/main.py frontend/src/pages/Login.tsx
- [ ] #27 ! grep -rn "FEISHU_APP_SECRET\s*=" platform/app/
- [ ] #28 grep -qE '@router\.(post|get)\("/(login|register|refresh|me)"' platform/app/routes/auth.py
- [ ] #29 pytest platform/tests/test_feishu_config.py -v
- [ ] #30 grep -q "feishu_app_id" platform/app/config.py
- [ ] #31 grep -q "feishu_base_url" platform/app/config.py
- [ ] #32 pytest platform/tests/test_oauth_state.py -v
- [ ] #33 test -f platform/app/services/oauth_state.py
- [ ] #34 grep -q "STATE_TTL_SECONDS" platform/app/services/oauth_state.py
- [ ] #35 pytest platform/tests/test_feishu_client.py -v
- [ ] #36 grep -q "from app.config import settings" platform/app/services/feishu_client.py
- [ ] #37 grep -q "get_full_user_info" platform/app/services/feishu_client.py
- [ ] #38 pytest platform/tests/test_feishu_user.py -v
- [ ] #39 grep -q "get_or_create_feishu_user" platform/app/auth/service.py
- [ ] #40 grep -q "async def create_or_update_sso_user" platform/app/auth/service.py
- [ ] #41 pytest platform/tests/test_feishu_auth_routes.py -v
- [ ] #42 grep -q "feishu/login" platform/app/routes/feishu_auth.py
- [ ] #43 grep -q "feishu/callback" platform/app/routes/feishu_auth.py
- [ ] #44 grep -q "feishu/token" platform/app/routes/feishu_auth.py
- [ ] #45 grep -q "create_access_token" platform/app/routes/feishu_auth.py
- [ ] #46 pytest platform/tests/test_feishu_router_registration.py -v
- [ ] #47 grep -q "feishu_auth" platform/app/main.py
- [ ] #48 grep -q "feishu" frontend/src/pages/Login.tsx
- [ ] #49 test -f frontend/src/pages/FeishuCallback.tsx
- [ ] #50 grep -q "useSearchParams" frontend/src/pages/FeishuCallback.tsx
- [ ] #51 grep -q '/login/feishu' frontend/src/App.tsx
- [ ] #52 pytest
- [ ] #53 pytest platform/tests/ -v
- [ ] #54 grep -rn "feishu" platform/app/config.py platform/app/services/feishu_client.py platform/app/services/oauth_state.py platform/app/routes/feishu_auth.py platform/app/main.py frontend/src/pages/Login.tsx
- [ ] #55 ! grep -rn "FEISHU_APP_SECRET\s*=" platform/app/
- [ ] #56 grep -qE '@router\.(post|get)\("/(login|register|refresh|me)"' platform/app/routes/auth.py
<!-- DOD:END -->
