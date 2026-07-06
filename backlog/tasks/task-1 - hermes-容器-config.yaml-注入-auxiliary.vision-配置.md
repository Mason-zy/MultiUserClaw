---
id: TASK-1
title: hermes 容器 config.yaml 注入 auxiliary.vision 配置
status: 'Basic: Done'
assignee: []
created_date: '2026-07-03 06:54'
updated_date: '2026-07-03 07:27'
labels:
  - 'kind:basic'
dependencies: []
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
为 hermes 用户容器生成的 config.yaml 注入 auxiliary.vision 段，让飞书图片消息能走平台 gateway 识图（当前报 RuntimeError: No LLM provider configured for task=vision）。

改 platform/app/container/manager.py:221 的 _build_hermes_config_yaml()，在 config dict 加 auxiliary.vision 段：provider=custom, model=openai/glm-5.1, base_url=settings.dedicated_hermes_default_base_url, api_key=settings.dedicated_hermes_default_api_key。

已实测：openai/glm-5.1 经 gateway 端到端 vision 成功（fallback 到 glm-5.2 正确识图）。model 必须带 openai/ 前缀（resolve_model_provider model_config.py:194 要求 provider/model 格式，否则 400 落到默认 deepseek 无 vision）。glm-5.1 已在 litellm model_provider_configs 表。

根因：当前 config 无 auxiliary 段，hermes vision auto 链（auxiliary_client.py:4625）因 DeepSeek 无 vision + 无 OpenRouter/Nous 凭证全 None → RuntimeError。配置缺失非 hermes bug。

DoD：扩展 platform/tests/test_dedicated_container_manager.py:115 test_build_hermes_runtime_files_support_platform_default_model，断言 config_yaml 含 auxiliary: 与 vision 段。pytest platform/tests/test_dedicated_container_manager.py 可跑。
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
# Proposal: 为 hermes 用户容器注入 auxiliary.vision 段，启用飞书图片识图

## Background

平台为每个 hermes 用户容器生成的 `config.yaml` 当前只配置主对话链（`model` 段：provider/base_url/default），完全没有 `auxiliary` 段。hermes 的 vision 子任务（飞书图片消息走识图）依赖 `auxiliary.vision` 显式配置或 `auto` 自动探测链；在平台专用容器里主 provider 是 `custom`+gateway 代理，vision `auto` 链探测不到任何已知聚合后端（OpenRouter / Nous）也没有裸 env key，最终在 `hermes-agent/agent/auxiliary_client.py:5630` 抛出 `RuntimeError: No LLM provider configured for task=vision provider=auto`，导致飞书图片消息识别直接失败。业务上用户在飞书里发图片得不到任何视觉理解回复，多模态能力空缺。

实测发现：让 hermes 的 vision 辅助客户端直连平台 gateway（`http://gateway:8080/llm/v1`）、走 `openai/glm-5.1` 模型，可端到端跑通图片识别——gateway（`platform/app/routes/llm.py:45` + `proxy.py:128`）按 `model` 字段的 `/` 前缀路由到 OpenAI 兼容后端（fjbigmodel），glow 5.1 具备视觉能力。

## Goals

1. `_build_hermes_config_yaml()`（`platform/app/container/manager.py:221`）生成的 YAML 含 `auxiliary.vision` 子段，字段为 `provider: custom`、`model: openai/glm-5.1`、`base_url` 取 `settings.dedicated_hermes_default_base_url`、`api_key` 取 `settings.dedicated_hermes_default_api_key`。
2. vision 段复用与主对话链相同的 gateway base_url / api_key，不引入新 setting、不新增 env 变量。
3. model 值固定带 `openai/` 前缀（`openai/glm-5.1`），满足 gateway 按 `/` 切分 provider 前缀的路由约定（`proxy.py:128`）。
4. 现有测试 `platform/tests/test_dedicated_container_manager.py:115`（`test_build_hermes_runtime_files_support_platform_default_model`）扩展，新增断言：解析出的 YAML 含 `auxiliary.vision` 段且四个字段值符合预期（provider/model/base_url/api_key）。
5. 现有测试全绿（`pytest platform/tests/test_dedicated_container_manager.py`），不破坏既有断言。

## Proposed Approach

在 `_build_hermes_config_yaml()` 构造的 `config` dict 中，于现有 `model` / `platform_toolsets` / `agent` 三段之外新增顶层 `auxiliary` 段，其下挂 `vision` 子段。`vision` 段四个字段：

- `provider: custom` —— 让 `_resolve_task_provider_model`（`auxiliary_client.py:5196`，`cfg_base_url and cfg_api_key` 同时存在分支）把这次调用识别为「自定义直连端点」，绕过 PROVIDER_REGISTRY 与 auto 探测链。
- `model: openai/glm-5.1` —— 透传给 OpenAI SDK 的 `model` 字段。gateway 在 `proxy.py:128` 用 `model.split("/", 1)[0]` 取 `openai` 作 provider 路由前缀，缺前缀会 fallback 到 `hermes` provider 走错后端。glm-5.1 是已实测可用的视觉模型。
- `base_url` = `settings.dedicated_hermes_default_base_url`（默认 `http://gateway:8080/llm/v1`，`config.py:58`）—— 与主对话链同一个 gateway 入口，复用既有平台代理与计费/限流。
- `api_key` = `settings.dedicated_hermes_default_api_key`（默认 `platform-proxy`，`config.py:59`）—— 与主链同一个鉴权令牌，不引入新凭证。

**为何走 gateway 而非直连 fjbigmodel**：gateway 是平台统一的多模型入口，承担路由/鉴权/计量/容灾；直连 fjbigmodel 会绕过这些能力、要求容器内分发 fjbigmodel 凭证、且与主链口径不一致。复用 gateway 让 vision 与主对话共用一套代理配置和凭证，改动面最小。

**为何必须带 `openai/` 前缀**：gateway 的路由协议要求 `model` 字段形如 `<provider>/<model_id>`，前缀决定走哪个后端 provider（OpenAI 兼容、Anthropic、DeepSeek 等）。裸 `glm-5.1` 会被 `proxy.py:128` 当作无前缀 fallback 到 `hermes` provider 而非 OpenAI 兼容链路，vision 调用会失败。`openai/` 前缀告诉 gateway 走 OpenAI chat completions 协议转发到 glm-5.1 后端。

## Trade-offs and Risks

**不做什么**：
- 不改 hermes-agent 代码（vision 解析链、auto 探测逻辑保持原样，靠 config 段显式声明绕开 auto）。
- 不改 litellm DB / 不新增 model provider 记录（vision 复用主链已注册的 gateway provider，不另开数据面）。
- 不配 OpenRouter / Nous（这两个是 hermes 内置的聚合 vision fallback，平台选择走自有 gateway 而非外部聚合，避免外部依赖与额度消耗）。
- 不新增 setting / env 变量（全复用既有 `dedicated_hermes_default_*`）。

**风险与边界**：
- **只对新创建/重建的容器生效**：`config.yaml` 在容器创建时一次性写入；已在运行的旧容器的 `config.yaml` 不会自动更新，老容器要发图需手动改容器内 `/opt/data/config.yaml` 或重建容器。这是配置注入方案的固有约束，不在本任务范围内自动化迁移。
- **glm-5.1 → glm-5.2 的 fallback 行为属 fjbigmodel 侧**：若上游 fjbigmodel 把 glm-5.1 别名指向 glm-5.2 或下线 5.1，是后端模型治理行为，平台只透传 model 字符串，不兜底版本兼容；如需切换模型改 `manager.py` 中 vision 段的 model 字面量即可。
- **provider 写 `custom` 而非 `openai`**：`custom` 让 hermes 走「显式 base_url + api_key 直连」分支（`auxiliary_client.py:5196`），不查 PROVIDER_REGISTRY；若误写 `openai` 会进入 direct-api alias 表把 base_url 强改到 `api.openai.com`（`auxiliary_client.py:5176-5182`），偏离 gateway 入口。
- **api_key 明文落 config.yaml**：与现有主链 `OPENAI_API_KEY` 落 env 文件、base_url 落 config.yaml 的处理一致，容器内文件本就含运行时凭证；不引入新的明文暴露面。

---

# Plan: hermes 容器 config.yaml 注入 auxiliary.vision 配置

Proposal: docs/proposals/proposal-hermes-auxiliary-vision-injection.md

## Phase A: 扩展测试断言 vision 段缺失（红）+ 注入 auxiliary.vision（绿）

### Tests (write first)

在 `platform/tests/test_dedicated_container_manager.py` 中：

1. 顶部 import 区（line 1-3 附近）新增 `import yaml`。
2. 在 `test_build_hermes_runtime_files_support_platform_default_model`（line 115）函数体末尾（现有断言之后）追加：
   - `parsed = yaml.safe_load(config_yaml)` —— 把 `_build_hermes_config_yaml()` 返回的 YAML 字符串解析回 dict，便于结构化断言 vision 子段。
   - 断言 `parsed["auxiliary"]["vision"]["provider"] == "custom"` —— 证明走 custom 直连分支（绕过 PROVIDER_REGISTRY 与 auto 探测）。
   - 断言 `parsed["auxiliary"]["vision"]["model"] == "openai/glm-5.1"` —— 证明带 `openai/` 前缀，满足 gateway `proxy.py:128` 按 `/` 切分 provider 前缀的路由约定。
   - 断言 `parsed["auxiliary"]["vision"]["base_url"] == "http://gateway:8080/llm/v1"` —— 证明复用 `settings.dedicated_hermes_default_base_url`（已被该测试 monkeypatch 设为 gateway 地址）。
   - 断言 `parsed["auxiliary"]["vision"]["api_key"] == "proxy-key"` —— 证明复用 `settings.dedicated_hermes_default_api_key`（已被该测试 monkeypatch 设为 `"proxy-key"`）。

先单独跑该测试应失败（红）：当前 `config` dict 无 `auxiliary` 段，`parsed["auxiliary"]` 抛 `KeyError`。

### Implementation

在 `platform/app/container/manager.py` 的 `_build_hermes_config_yaml()`（line 221）构造的 `config` dict 中，于 `agent` 段之后新增顶层 `auxiliary` 段：

```python
config = {
    "model": {
        "default": settings.default_model,
        "provider": settings.dedicated_hermes_default_provider,
        "base_url": settings.dedicated_hermes_default_base_url,
    },
    "platform_toolsets": {
        "api_server": _hermes_api_toolsets(),
    },
    "agent": {
        "reasoning_effort": settings.hermes_reasoning_effort,
        "service_tier": settings.hermes_service_tier,
    },
    "auxiliary": {
        "vision": {
            "provider": "custom",
            "model": "openai/glm-5.1",
            "base_url": settings.dedicated_hermes_default_base_url,
            "api_key": settings.dedicated_hermes_default_api_key,
        },
    },
}
```

四个字段来源：
- `provider: "custom"`（字面量）—— 让 hermes `_resolve_task_provider_model`（`hermes-agent/agent/auxiliary_client.py:5196`，`cfg_base_url and cfg_api_key` 同时存在的分支）把 vision 调用识别为「自定义直连端点」，绕过 PROVIDER_REGISTRY 与 auto 探测链。不写 `openai` 是为了避免进入 direct-api alias 表把 base_url 强改到 `api.openai.com`（`auxiliary_client.py:5176-5182`）。
- `model: "openai/glm-5.1"`（字面量）—— 透传给 OpenAI SDK 的 `model` 字段。`openai/` 前缀是 gateway 路由协议要求（`proxy.py:128` 用 `model.split("/", 1)[0]` 取前缀决定走哪个后端 provider），缺前缀会 fallback 到 `hermes` provider 走错链路。glm-5.1 已实测具备视觉能力。
- `base_url: settings.dedicated_hermes_default_base_url`（默认 `http://gateway:8080/llm/v1`，`config.py:58`）—— 与主对话链同一个 gateway 入口，复用平台代理/鉴权/计量。
- `api_key: settings.dedicated_hermes_default_api_key`（默认 `platform-proxy`，`config.py:59`）—— 与主链同一个鉴权令牌，不引入新凭证。

`yaml.safe_dump(config, allow_unicode=True, sort_keys=False)` 会按插入顺序输出，`auxiliary` 段在 `agent` 段之后、文件末尾。

### DoD

- [ ] `pytest platform/tests/test_dedicated_container_manager.py::test_build_hermes_runtime_files_support_platform_default_model`
- [ ] `pytest platform/tests/test_dedicated_container_manager.py`

## Constraints

- 不改 hermes-agent 代码（vision 解析链、`auxiliary_client.py` auto 探测逻辑保持原样，靠 config 段显式声明绕开 auto）。
- 不改 litellm DB / 不新增 model provider 记录（vision 复用主链已注册的 gateway provider）。
- 不配 OpenRouter / Nous（外部聚合 fallback）。
- 不新增 setting / env 变量（全复用既有 `dedicated_hermes_default_*`）。
- 只对新建/重建容器生效，老容器不自动迁移（`config.yaml` 在容器创建时一次性写入，超出本任务范围）。
- `service.py` / `admin.py` / `docker-compose.yml` / 前端等其他文件不动。
- vision 段 model 字面量硬编码为 `openai/glm-5.1`（如需切换模型直接改 `manager.py` 字面量，不兜底 fjbigmodel 侧版本兼容）。

## Acceptance Gate

- [ ] `pytest`
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Proposal approved. Starting plan draft.

Plan review iteration 1: APPROVED

claimed: 2026-07-03T07:14:11Z

Completed: 2026-07-03T07:27:23Z
workerLoop pre-merge DoD: PASS
<!-- SECTION:NOTES:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 pytest platform/tests/test_dedicated_container_manager.py::test_build_hermes_runtime_files_support_platform_default_model
- [ ] #2 pytest platform/tests/test_dedicated_container_manager.py
- [ ] #3 pytest
<!-- DOD:END -->
