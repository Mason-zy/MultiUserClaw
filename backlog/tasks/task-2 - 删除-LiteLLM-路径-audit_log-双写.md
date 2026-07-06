---
id: TASK-2
title: 删除 LiteLLM 路径 audit_log 双写
status: 'Basic: Done'
assignee: []
created_date: '2026-07-03 07:08'
updated_date: '2026-07-03 07:27'
labels:
  - 'kind:basic'
dependencies: []
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
platform/app/llm_proxy/service.py 的 LiteLLM 路径在 _record_usage（内部已写 audit_log，:557，detail 含 provider_id/upstream_model）之后又写了冗余 write_audit_log（detail 更少），导致每个 LiteLLM 调用产生 2 条 llm_call audit_log + 1 条 UsageRecord。Anthropic 路径（:664）只调 _record_usage 一次是干净的。

删两处冗余：
- :770-781 流式路径的 await write_audit_log(...) 块 + :782 db.commit()（_record_usage 内部 :571 已 commit）
- :801-812 非流式路径的 await write_audit_log(...) 块 + :813 db.commit()
保留 _record_usage 调用。

实测影响：Alice 容器 audit_logs llm_call=213 vs usage_records=199，差距 14 条即 LiteLLM 双写所致。

DoD：扩展 platform/tests/test_llm_proxy.py，mock write_audit_log 计数，断言成功 LiteLLM 调用只产生 1 条 llm_call audit_log（非 2）。pytest platform/tests/test_llm_proxy.py 可跑（litellm/jose 等依赖已装）。service.py 是 upstream 热点，改动用 # LOCAL: 标记。
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
# Proposal: 删除 LiteLLM 路径 audit_log 双写

## Background

`platform/app/llm_proxy/service.py` 的 LiteLLM 路径（流式 + 非流式）在成功调用后存在冗余双写：先调 `_record_usage`（其内部 `service.py:557` 已写入一条更完整的 `write_audit_log(action="llm_call")`，含 `provider_id` / `upstream_model` / `total_tokens`，并于 `:571` `db.commit()`），随后外部又紧接着再写一条 detail 更少的 `write_audit_log` + 再 `commit` 一次。

后果：每次成功 LiteLLM 调用产生 **2 条 `audit_logs` + 1 条 `usage_records`**，audit 与 usage 计数口径错乱。实测 Alice 实例 `audit_logs` 213 条 vs `usage_records` 199 条，差 14 条正是双写残留。计量/审计/对账均受影响，且外部那条 detail 缺 `provider_id` / `upstream_model`，价值更低。Anthropic 路径（`service.py:664-676`）已正确只调一次 `_record_usage`、无外部 `write_audit_log`，可作对照。

## Goals

1. 删除流式 `service.py:770-782` 的冗余 `write_audit_log` 块 + `db.commit()`，保留 `:760 _record_usage` 调用。
2. 删除非流式 `service.py:801-813` 的冗余 `write_audit_log` 块 + `db.commit()`，保留 `:791 _record_usage` 调用。
3. 保留 `_record_usage` 内部 `service.py:557-570` 的 audit_log 写入不变（这是唯一权威落库点）。
4. 扩展 `platform/tests/test_llm_proxy.py`：新增测试断言成功 LiteLLM 调用 `write_audit_log` 恰好被调用 1 次（当前代码 == 2，红；删除后 == 1，绿）。
5. 现有测试全绿（`pytest platform/tests/test_llm_proxy.py`）。

## Proposed Approach

删除 `service.py:770-782`（流式 finally 块内 `_record_usage` 之后的 `write_audit_log` + `commit`）与 `service.py:801-813`（非流式 `_record_usage` 之后的 `write_audit_log` + `commit`）两段冗余代码。

`_record_usage` 内部 `service.py:557-570` 已写更完整的 `audit_log`：detail 含 `provider_id` / `upstream_model` / `total_tokens`，并于 `:571` `commit`。外部 :770/:801 那条 detail 更少（仅 stream / input / output / total），是早期 `_record_usage` 尚未内嵌 audit_log 时遗留的并行写入，现已冗余。Anthropic 路径 `service.py:664-676` 只调一次 `_record_usage`、无外部 `write_audit_log`，即目标终态——本次把 LiteLLM 两条路径对齐到 Anthropic 路径的写法。

## Trade-offs and Risks

**不做什么（明确范围边界）：**
- 不改 `_record_usage` 函数本身（`service.py:534-571`）。
- 不改 Anthropic 路径（`service.py:664-676`，已正确）。
- 不改 usage 记账 / quota 逻辑（`UsageRecord` 仍由 `_record_usage:548-556` 唯一写入）。
- 失败调用（`acompletion` 抛异常或 HTTP 502）不落 audit_log / usage 是现有设计取舍，不在本任务范围。

**风险：**
- `service.py` 是 upstream 热点（fork 自 `johnson7788/MultiUserClaw`），改动点用 `# LOCAL: 删除冗余 audit_log 双写` 标记，rebase 时易于识别移植。
- `_record_usage` 在 `total <= 0` 或 `user is None` 时提前 return（`service.py:546-547`），此时 audit_log 也不写——这是现有行为，本任务不改变。

---

# Plan: 删除 LiteLLM 路径 audit_log 双写

Proposal: docs/proposals/proposal-delete-litellm-audit-log-double-write.md

## Phase A: 扩展测试断言双写存在（红）+ 删冗余 write_audit_log（绿）

### Tests (write first)

在 `platform/tests/test_llm_proxy.py` 新增测试 `test_successful_litellm_call_writes_audit_log_exactly_once`：

- `monkeypatch.setattr(service, "_resolve_provider", lambda _m: ("openai/gpt-5.4", "openai-key", None, None))`（走 LiteLLM 分支，非 Anthropic）
- `monkeypatch.setattr(service.settings, "dev_openclaw_url", "http://dev-openclaw")`（跳过鉴权，user=None → 需要构造 user：见下）
- `monkeypatch.setattr(service, "acompletion", fake_acompletion)`，`fake_acompletion` 返回 `SimpleNamespace(model_dump=lambda: {"ok": True}, usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30))`（**关键：必须带真实 usage，否则 `:590 usage is None` 不进 `_record_usage`，测不到双写**）
- **不 mock `_record_usage`**（让它真实执行，其内部 `:557` 调被 mock 的 `write_audit_log`），只 mock 外围：`db` 用 `AsyncMock()`（`db.add` / `db.commit` 为 no-op）；`service.write_audit_log` mock 成计数器 `calls = []; AsyncMock(side_effect=lambda *a, **k: calls.append(k))`。
- 构造 user：`monkeypatch.setattr(service, "decode_token", lambda _t: {"type": "access", "sub": "u1"})` + `db.execute` 返回 fake user（`SimpleNamespace(id="u1", is_active=True)`）；`monkeypatch.setattr(service, "_check_quota", AsyncMock())` 绕过 quota。
- 调 `proxy_chat_completion(stream=False)`，断言 `len(calls) == 1`（当前代码 `_record_usage` 内部 `:557` 写 1 次 + 外部 `:801` 再写 1 次 == 2，**红**；删 `:801-813` 后 == 1，**绿**）。

### Implementation

- 删 `service.py:770-782`（流式 finally 块 `_record_usage` 之后的 `write_audit_log` 块 + `await db.commit()`），保留 `:760-769 _record_usage` 调用。
- 删 `service.py:801-813`（非流式 `_record_usage` 之后的 `write_audit_log` 块 + `await db.commit()`），保留 `:791-800 _record_usage` 调用。
- 在两处删除点加 `# LOCAL: 删除冗余 audit_log 双写（_record_usage 内部已写，见 :557）` 注释，方便 upstream rebase 识别。
- 不动 `_record_usage`（`:534-571`）、Anthropic 路径（`:664-676`）、`UsageRecord` 写入。

### DoD

- [ ] `pytest platform/tests/test_llm_proxy.py`

## Constraints

- 不改 `_record_usage` / Anthropic 路径 / usage 记账逻辑；失败调用落库不在范围；保留 service.py 其余逻辑。
- `service.py` 是 upstream 热点，所有改动用 `# LOCAL:` 标记。

## Acceptance Gate

- [ ] `pytest`
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
claimed: 2026-07-03T07:14:12Z

DoD #1: PASS — pytest platform/tests/test_llm_proxy.py (9/9 passed)
workerLoop 接手实现（原 agent API 错中断），commit 3e7412bd4

Completed: 2026-07-03T07:27:24Z
workerLoop pre-merge DoD: PASS
<!-- SECTION:NOTES:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 pytest platform/tests/test_llm_proxy.py
- [ ] #2 pytest
<!-- DOD:END -->
