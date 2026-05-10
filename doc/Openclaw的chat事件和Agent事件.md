

# Openclaw的chat 事件和 Agent事件

在目录 openclaw` 中，我需要理解 “chat” 事件和 “Agent” 事件系统。全面探索：

1.  查看 `src/` 目录结构以了解项目布局
2.  搜索与 “chat” 事件和 “Agent” 事件相关的文件和代码——包括事件发射器、事件处理器、事件类型
3.  了解聊天消息如何流经系统（从用户输入到 LLM 响应）
4.  了解 Agent 事件如何工作（Agent 生命周期、Agent 切换等）
5.  搜索关键词，如 “emit”、“event”、“chat”、“agent”、“onChat”、“onAgent”、“EventEmitter” 等
6.  同时检查 `packages/` 目录中相关的事件系统代码
7.  查找任何事件类型定义或接口

返回全面的解释：
-   事件系统架构（使用了什么事件总线/发射器）
-   “chat” 事件是什么，何时触发，携带什么数据，以及它的生命周期是什么样的
-   “Agent” 事件是什么，何时触发，携带什么数据，以及它的生命周期是什么样的
-   插件/扩展如何接入这些事件
-   关键代码的相关文件路径和行号

思考：让我全面探索 OpenClaw 项目以理解事件系统架构。我将从目录结构开始，然后深入研究相关代码。
我将从广泛探索项目结构开始，然后深入研究事件系统的细节。
→ 读取 openclaw
→ 读取 openclaw/src

思考：项目结构庞大。现在让我探索与事件相关的关键目录：`src/chat/`、`src/agents/`，并查找事件相关文件。
→ 读取 openclaw/src/chat
→ 读取 openclaw/src/agents
✱ 在 openclaw/src 中 grep “EventEmitter”（80 处匹配）
✱ 在 openclaw/src 中 grep “onChat|onAgent”（703 处匹配）

思考：现在让我查看事件系统的关键文件。主要关注的区域是：
1.  `src/infra/agent-events.ts` - 这似乎是 Agent 事件的主要事件系统
2.  `src/gateway/` - 可能包含聊天事件系统
3.  `src/plugin-sdk/` - 插件 SDK 事件类型
4.  `src/plugins/` - 插件运行时事件钩子
5.  事件类型定义
让我更具体地搜索这些。
✱ 在 openclaw/src 中 glob “**/agent-events*”（2 处匹配）
✱ 在 openclaw/src 中 glob “**/gateway/**/*.ts”（100 处匹配）
→ 读取 openclaw/src/gateway
→ 读取 openclaw/src/infra

思考：现在我找到了关键文件。让我阅读核心事件系统文件：
1.  `src/infra/agent-events.ts` - Agent 事件系统
2.  `src/gateway/events.ts` - 网关事件（可能是聊天事件）
3.  `src/gateway/server-chat.ts` - 聊天服务器逻辑
4.  `src/gateway/hooks.ts` 和 `src/gateway/hooks.types.ts` - 钩子类型
5.  `src/gateway/server-session-events.ts` - 会话事件
6.  查找聊天事件类型
让我也搜索更具体的模式。
让我阅读核心事件系统文件：
→ 读取 openclaw/src/infra/agent-events.ts
↳ 已加载 openclaw/AGENTS.md
→ 读取 openclaw/src/gateway/events.ts
→ 读取 openclaw/src/gateway/hooks.types.ts

思考：现在让我深入研究事件系统。让我阅读：
1.  `src/shared/listeners.ts` - `agent-events` 使用的底层监听器机制
2.  `src/gateway/server-chat.ts` - 主要的聊天处理器
3.  `src/gateway/server-session-events.ts` - 会话事件
4.  `src/gateway/server-node-events.ts` - 节点事件
5.  `src/infra/heartbeat-events.ts` - 心跳事件
6.  `src/infra/diagnostic-events.ts` - 诊断事件
7.  `src/infra/system-events.ts` - 系统事件
8.  `src/agents/internal-events.ts` - 内部 Agent 事件
→ 读取 openclaw/src/shared/listeners.ts
→ 读取 openclaw/src/gateway/server-chat.ts
→ 读取 openclaw/src/gateway/server-session-events.ts
→ 读取 openclaw/src/agents/internal-events.ts

思考：现在让我查看更具体的文件以完善画面。我需要查看：
1.  `src/gateway/server.ts` 和 `src/gateway/server.impl.ts` - 了解事件处理程序如何连接
2.  `src/gateway/server-broadcast.ts` - 广播机制
3.  `src/agents/subagent-lifecycle-events.ts` - Agent 子生命周期事件
4.  `src/sessions/session-lifecycle-events.ts` - 会话生命周期事件
5.  `src/hooks/` - 插件钩子系统的钩子目录
6.  插件 SDK 事件系统
7.  `src/infra/diagnostic-events.ts` 和 `src/infra/heartbeat-events.ts` - 其他事件系统
8.  `src/gateway/hooks.ts` - 插件钩子
→ 读取 openclaw/src/gateway/server-broadcast.ts
→ 读取 openclaw/src/gateway/hooks.ts [限制=100]
→ 读取 openclaw/src/agents/internal-event-contract.ts
→ 读取 openclaw/src/hooks

思考：现在让我查看插件 SDK 中的事件和钩子机制，以及钩子类型。
→ 读取 openclaw/src/hooks/plugin-hooks.ts
→ 读取 openclaw/src/hooks/types.ts
→ 读取 openclaw/src/plugin-sdk
→ 读取 openclaw/src/plugins/runtime/types-core.ts
↳ 已加载 openclaw/src/plugins/AGENTS.md

思考：现在让我查看特定的事件相关部分。我需要深入研究：
1.  服务器如何通过事件系统路由聊天事件
2.  用于连接的 `server.ts` 和 `server.impl.ts`
3.  钩子映射以及钩子如何与事件交互
4.  插件如何监听事件
让我查看整合所有内容的关键文件。
→ 读取 openclaw/src/gateway/server.impl.ts [限制=100]
→ 读取 openclaw/src/gateway/server.ts [限制=100]
→ 读取 openclaw/src/gateway/server-methods/chat.ts [限制=100]
↳ 已加载 openclaw/src/gateway/server-methods/AGENTS.md
→ 读取 openclaw/src/gateway/server-runtime-state.ts [限制=100]

思考：现在让我查看关键的连接部分——Agent 事件监听器如何在服务器中附加，并查看 `server-runtime-subscriptions.ts` 文件，该文件可能连接了所有内容。
→ 读取 openclaw/src/gateway/server-runtime-subscriptions.ts
→ 读取 openclaw/src/gateway/server.impl.ts [偏移量=300, 限制=200]
→ 读取 openclaw/src/sessions/transcript-events.ts

思考：现在让我查看 `chat.ts` 方法中如何使用 “chat” 事件以了解完整的生命周期，并查看心跳事件、诊断事件、系统事件和其他事件类型。
→ 读取 openclaw/src/infra/heartbeat-events.ts
→ 读取 openclaw/src/infra/diagnostic-events.ts
→ 读取 openclaw/src/infra/system-events.ts
→ 读取 openclaw/src/sessions/session-lifecycle-events.ts

思考：现在让我更仔细地查看 `server-methods/chat.ts` 以了解聊天流程，并查看 `server.ts`（主网关入口）以了解事件如何连接到 WebSocket 客户端。具体来说，我想看看聊天事件是如何发射给 WebSocket 客户端的。让我也查看 Agent 事件的测试文件以获得深入理解。
现在让我查看聊天方法是如何实现的，以及从用户输入开始的聊天流程：
→ 读取 openclaw/src/gateway/server-methods/chat.ts [偏移量=101, 限制=200]
→ 读取 openclaw/src/infra/agent-events.test.ts
→ 读取 openclaw/src/gateway/server-runtime-state.ts [偏移量=100]

思考：现在让我查看 `server.impl.ts` 的其余部分，那里启动了事件订阅，并查看 `server-methods/chat.ts` 中的 `chat` 方法如何触发聊天流程。我需要了解完整的图景。
→ 读取 openclaw/src/gateway/server.impl.ts [偏移量=500, 限制=150]
→ 读取 openclaw/src/gateway/server-methods/chat.ts [偏移量=301, 限制=200]
→ 读取 openclaw/src/gateway/agent-event-assistant-text.ts

思考：现在让我查看 `chat.send` 处理程序以了解用户输入如何启动流程，以及事件如何从 Agent 发射。另外，让我查看 `broadcast(“chat”, ...)` 函数是如何定义和使用的，以及 Agents 如何发射生命周期事件。
让我查看 `chat.send` 处理程序和 Agent 生命周期事件发射：
→ 读取 openclaw/src/gateway/server-methods/chat.ts [偏移量=501, 限制=300]
✱ 在 openclaw/src/agents 中 grep “emitAgentEvent.*stream.*lifecycle”
✱ 在 openclaw/src/agents 中 grep “emitAgentEvent”（47 处匹配）

思考：让我查看关键的生命周期和消息事件发射器，以了解 Agent 事件的完整生命周期。
→ 读取 openclaw/src/agents/pi-embedded-subscribe.handlers.lifecycle.ts
→ 读取 openclaw/src/agents/pi-embedded-subscribe.handlers.messages.ts

思考：现在让我查看在哪里发射了带有 “tool” 流的 `emitAgentEvent`，以了解 Agent 事件的完整图景。另外，让我检查插件如何连接到 Agent 事件。
→ 读取 openclaw/src/agents/pi-embedded-subscribe.handlers.tools.ts [限制=100]
→ 读取 openclaw/src/plugins/runtime/runtime-events.ts
→ 读取 openclaw/src/agent-event-assistant-text.ts
未找到文件：/Users/admin/Documents/yifu/nanobot/openclaw/src/agent-event-assistant-text.ts
→ 读取 openclaw/src/agents/subagent-lifecycle-events.ts

思考：现在让我查看其他插件和钩子文件，以及 `tasks/task-registry.ts`，了解插件如何使用 `onAgentEvent`。
→ 读取 openclaw/src/tasks/task-registry.ts [偏移量=1290, 限制=30]
→ 读取 openclaw/src/plugins/runtime/types.ts [限制=50]
→ 读取 openclaw/src/agents/pi-embedded-subscribe.ts [限制=50]

思考：现在让我查看剩余的部分——WebSocket 事件类型 `broadcast(“chat”, ...)` 和 `broadcast(“agent”, ...)` 及其有效负载。让我也检查网关协议中的聊天事件类型定义。
让我检查 WebSocket 协议类型以及聊天/Agent 事件在线上是如何定义的：
✱ 在 openclaw/src/gateway/protocol 中 grep “”chat“|”agent“|”session\.message“|”session\.tool“”
✱ 在 openclaw/src 中 glob “**/gateway/protocol/**/*.ts”（31 处匹配）

思考：让我查看协议模式框架和主要模式，以了解 WebSocket 事件类型。
→ 读取 openclaw/src/gateway/protocol/schema/frames.ts
↳ 已加载 openclaw/src/gateway/protocol/AGENTS.md
→ 读取 openclaw/src/gateway/protocol/schema.ts
✱ 在 openclaw/src/gateway 中 grep “GATEWAY_EVENTS|server-methods-list”（6 处匹配）

思考：让我查看 `server-methods-list.ts` 以查看 `GATEWAY_EVENTS` 列表。
→ 读取 openclaw/src/gateway/server-methods-list.ts [偏移量=120]

思考：现在让我获取 `GATEWAY_EVENTS` 的完整列表并读取文件的开头。
→ 读取 openclaw/src/gateway/server-methods-list.ts

思考：现在我对事件系统有了非常全面的理解。让我也检查插件 SDK 中的 `onAgentEvent` 以及插件如何连接。
让我验证插件 SDK 如何暴露事件系统，并检查文档参考：
✱ 在 openclaw/src/plugin-sdk 中 grep “onAgentEvent”
✱ 在 openclaw/src/plugin-sdk 中 grep “onSessionTranscriptUpdate”
→ 读取 openclaw/src/plugins/hook-runner-global.ts [限制=60]

思考：现在我对事件系统有了全面的理解。让我更深入地查看插件钩子，特别是 `src/plugins/hooks.ts` 和 `src/plugins/types.ts`，以了解插件可以监听的生命周期事件。
→ 读取 openclaw/src/plugins/hooks.ts [限制=80]
✱ 在 openclaw/src/plugins 中 grep “PluginHook|AfterToolCall|BeforeToolCall|GatewayStart”（169 处匹配）

思考：现在我对事件系统有了非常全面的理解。让我将我的发现整理成一个清晰的结构。让我也查看钩子运行程序以了解它如何分发事件，并读取插件钩子类型以获取完整列表。
让我检查所有插件钩子名称的列表以及它们是如何分发的：
→ 读取 openclaw/src/plugins/types.ts [偏移量=2306, 限制=80]
→ 读取 openclaw/src/plugins/hooks.ts [偏移量=81, 限制=100]

思考：现在我对整个事件系统有了非常透彻的理解。现在让我整理出全面的解释。
让我也检查将钩子映射到内部事件的内部钩子，以及 Agent 事件的测试文件，以验证我的理解。
现在我已经收集了足够的信息。以下是我的全面分析：
---
**OpenClaw 事件系统架构全面分析**

**1. 整体架构**

OpenClaw 项目有一个多层级的事件系统，包含三种不同的事件机制：

| 层级                           | 机制                                | 文件                                           | 模式                                                    |
| :----------------------------- | :---------------------------------- | :--------------------------------------------- | :------------------------------------------------------ |
| **Agent 事件**                 | 自定义监听器模式（基于 `Set`）      | `src/infra/agent-events.ts`                    | 通过 `emitAgentEvent()` / `onAgentEvent()` 发布/订阅    |
| **网关事件**（WebSocket 广播） | 广播给已连接的 WebSocket 客户端     | `src/gateway/server-broadcast.ts`              | 向所有 WebSocket 客户端广播 `broadcast(event, payload)` |
| **插件钩子**                   | 插件注册的生命周期回调钩子          | `src/plugins/hooks.ts`, `src/plugins/types.ts` | 命名钩子，如 `before_tool_call`, `agent_end`            |
| **其他内部事件**               | 特定子系统的基于 `Set` 的监听器模式 | 多个文件                                       | 心跳、诊断、会话生命周期、转录本事件                    |

这些系统并非基于 Node.js 的 `EventEmitter`（测试模拟除外）。它们使用一个轻量级的自定义模式：
- `src/shared/listeners.ts` —— 提供 `registerListener(set, listener)` 和 `notifyListeners(set, event)` 辅助函数
- 状态通过 `Symbol.for(...)` 键保存在全局单例中（参见 `src/shared/global-singleton.ts`）

---

**2. Agent 事件 (`src/infra/agent-events.ts`)**

这是 Agent 运行期间所有内部事件的实时事件总线。

**架构**
- 数据结构：一个单例 `AgentEventState` 包含：
  - `seqByRun`: `Map<string, number>` —— 每个 `runId` 的序列计数器（单调递增，从 1 开始）
  - `listeners`: `Set<(evt: AgentEventPayload) => void>` —— 所有已注册的监听器
  - `runContextById`: `Map<string, AgentRunContext>` —— 每个活动运行的元数据

**Agent 事件类型 (`AgentEventStream`)**
```typescript
"lifecycle" | "tool" | "assistant" | "error" | "item" | "plan" |
"approval" | "command_output" | "patch" | "compaction" | "thinking" | (string & {})
```

**核心事件负载 (`AgentEventPayload`)**
```typescript
type AgentEventPayload = {
  runId: string;         // 标识单个 Agent "运行"
  seq: number;           // 每个 runId 的单调序列号 (1, 2, 3, ...)
  stream: AgentEventStream; // 事件类型
  ts: number;            // 时间戳
  data: Record<string, unknown>; // 特定事件的有效负载
  sessionKey?: string;   // 会话键（对于不可见的运行省略）
};
```

**运行上下文 (`AgentRunContext`)**
```typescript
type AgentRunContext = {
  sessionKey?: string;
  verboseLevel?: VerboseLevel;
  isHeartbeat?: boolean;
  isControlUiVisible?: boolean;  // 如果为 false，则会从事件中剥离 sessionKey
  registeredAt?: number;
  lastActiveAt?: number;
};
```

**关键函数**

| 函数                                             | 用途                                          |
| :----------------------------------------------- | :-------------------------------------------- |
| `emitAgentEvent(event)`                          | 发射原始 Agent 事件（自动分配 `seq` 和 `ts`） |
| `emitAgentItemEvent({runId, data, sessionKey?})` | 发射类型化的 "item" 事件                      |
| `emitAgentPlanEvent(...)`                        | 发射类型化的 "plan" 事件                      |
| `emitAgentApprovalEvent(...)`                    | 发射类型化的 "approval" 事件                  |
| `emitAgentCommandOutputEvent(...)`               | 发射类型化的 "command_output" 事件            |
| `emitAgentPatchSummaryEvent(...)`                | 发射类型化的 "patch" 事件                     |
| `registerAgentRunContext(runId, context)`        | 在事件流动前注册运行的元数据                  |
| `getAgentRunContext(runId)`                      | 查找运行元数据                                |
| `clearAgentRunContext(runId)`                    | 运行结束后清理                                |
| `sweepStaleRunContexts(maxAgeMs)`                | 定期清理孤立的上下文                          |
| `onAgentEvent(listener)`                         | 订阅所有 Agent 事件；返回取消订阅函数         |

**Agent 事件生命周期**

典型的 Agent 运行生命周期按顺序发射这些事件：
```text
LIFECYCLE (phase: "start")
  └─ 注册运行上下文
ITEM (phase: "start", kind: "tool"/"command"/...)   ── 工具开始
PLAN (phase: "update")                               ── 计划更新
ASSISTANT (data: {text, delta})                       ── 流式文本块
TOOL / COMMAND_OUTPUT / PATCH                         ── 工具生命周期
APPROVAL (phase: "requested"/"resolved")              ── 审批流程
ITEM (phase: "end")                                   ── 工具结束
COMPACTION (phase: "start"/"end")                     ── 会话压缩
LIFECYCLE (phase: "end" 或 phase: "error")
  └─ 清理运行上下文
```

---

**3. 聊天事件（WebSocket 广播）**

"聊天"事件是发送给 WebSocket 客户端（控制界面、CLI、移动应用）的广播事件。它们与 Agent 事件不同——`src/gateway/server-chat.ts` 中的 `createAgentEventHandler` 桥接了这两个系统。

**桥接器：`server-runtime-subscriptions.ts`（第 17-84 行）**

这是连接点：
```typescript
// src/gateway/server-runtime-subscriptions.ts:36-51
const agentUnsub = onAgentEvent(
  createAgentEventHandler({
    broadcast,           // 广播给所有 WS 客户端
    broadcastToConnIds,  // 广播给特定的 connId
    nodeSendToSession,   // 发送给节点（移动端）会话
    agentRunSeq,         // 跟踪序列以保证顺序
    chatRunState,        // 管理聊天缓冲区状态
    resolveSessionKeyForRun,
    clearAgentRunContext,
    toolEventRecipients,
    sessionEventSubscribers,
  }),
);
```

**`createAgentEventHandler()` 位于 `src/gateway/server-chat.ts`（第 474-1022 行）**

该处理程序监听所有 Agent 事件并：
1. 将 Agent 事件转换为面向 WS 客户端的聊天事件
2. 管理文本缓冲——累积助手文本增量并限制广播（第 726 行，150ms 限制）
3. 处理生命周期转换——当 `lifecycle.phase === “error”` 或 `lifecycle.phase === “end”` 时，完成聊天运行
4. 管理工具事件路由——将工具事件发送给已注册的 WS 接收者和会话订阅者

**聊天事件负载（WS 线路格式）**

增量流（`event: “chat”`, `state: “delta”`）：
```json
{
  "runId": "...",
  "sessionKey": "...",
  "seq": 42,
  "state": "delta",
  "message": {
    "role": "assistant",
    "content": [{ "type": "text", "text": "部分响应..." }],
    "timestamp": 1234567890
  }
}
```

最终消息（`event: “chat”`, `state: “final”`）：
```json
{
  "runId": "...",
  "sessionKey": "...",
  "seq": 43,
  "state": "final",
  "stopReason": "end_turn",
  "message": {
    "role": "assistant",
    "content": [{ "type": "text", "text": "完整响应..." }],
    "timestamp": 1234567890
  }
}
```

错误（`event: “chat”`, `state: “error”`）：
```json
{
  "runId": "...",
  "sessionKey": "...",
  "seq": 43,
  "state": "error",
  "errorMessage": "...",
  "errorKind": "timeout"
}
```

Agent 事件（`event: “agent”`）——直接从 `AgentEventPayload` 中继：
```json
{
  "runId": "...",
  "sessionKey": "...",
  "seq": 1,
  "stream": "lifecycle",
  "data": { "phase": "start" },
  "ts": 1234567890
}
```

**已注册的网关事件**

所有 WebSocket 事件都列在 `src/gateway/server-methods-list.ts:138-163` 中：
```text
"agent", "chat", "session.message", "session.tool", "sessions.changed",
"presence", "tick", "talk.mode", "shutdown", "health", "heartbeat",
"cron", "node.pair.requested", "node.pair.resolved", "node.invoke.request",
"device.pair.requested", "device.pair.resolved", "voicewake.changed",
"exec.approval.requested", "exec.approval.resolved",
"plugin.approval.requested", "plugin.approval.resolved",
"update.available"
```

---

### 4. 完整的聊天消息流程（从用户输入到 LLM 响应）

1.  **用户通过 `chat.send` 方法发送消息（WebSocket RPC）**
    - 处理程序：`src/gateway/server-methods/chat.ts`（约第 1700 行以上）
    - 验证输入，解析会话、Agent、模型
    - 通过 `dispatchInboundMessage()` 分发到自动回复系统

2.  **嵌入式 Agent 运行开始**
    - `src/agents/pi-embedded-subscribe.ts` 编排运行
    - `src/agents/pi-embedded-subscribe.handlers.lifecycle.ts:24` 中的 `handleAgentStart()` 发射：
      ```typescript
      emitAgentEvent({ runId, stream: "lifecycle", data: { phase: "start" } })
      ```
    - 这通过 `onAgentEvent` → `createAgentEventHandler` → `broadcast(“chat”, ...)` 和 `broadcast(“agent”, ...)` 流向 WS 客户端

3.  **LLM 流式响应**
    - `src/agents/pi-embedded-subscribe.handlers.messages.ts:197` 中的 `handleMessageUpdate()` 处理助手消息更新
    - 在 `text_delta` 事件上，它发射：
      ```typescript
      emitAgentEvent({ runId, stream: "assistant", data: { text, delta } })
      ```
    - 聊天事件处理程序的 `emitChatDelta()`（第 682 行）限制并广播 `event: “chat”, state: “delta”`

4.  **工具执行**
    - `src/agents/pi-embedded-subscribe.handlers.tools.ts` 中的 `handleToolStart()` / `handleToolEnd()`
    - 发射：
      - `emitAgentItemEvent()`，包含 `kind: “tool”`，阶段 `“start”` / `“update”` / `“end”`
      - `emitAgentCommandOutputEvent()` 用于执行输出
      - `emitAgentApprovalEvent()` 用于审批流程
    - 这些流向 WS 客户端，作为 `event: “agent”` 并带有 `stream: “item”`、`stream: “tool”` 等

5.  **运行完成**
    - `pi-embedded-subscribe.handlers.lifecycle.ts:38` 中的 `handleAgentEnd()` 发射：
      ```typescript
      emitAgentEvent({ runId, stream: "lifecycle", data: { phase: "end" } })
      ```
    - 聊天处理程序的 `finalizeLifecycleEvent()` 广播 `event: “chat”, state: “final”` 和 `event: “sessions.changed”`

---

**5. 插件钩子系统（`src/plugins/hooks.ts` 和 `src/plugins/types.ts`）**

**注册**

插件通过插件清单的 `hooks` 数组或编程方式注册生命周期钩子。`HookRunner` 将事件分发给已注册的插件钩子：
```typescript
// 插件像这样注册钩子：
plugin.on("before_tool_call", async (event, context) => { ... });
```

**完整的插件钩子名称列表**

`src/plugins/types.ts:2306-2335`：

| 钩子名称                   | 事件类型                                | 触发时机                        |
| :------------------------- | :-------------------------------------- | :------------------------------ |
| `before_model_resolve`     | `PluginHookBeforeModelResolveEvent`     | LLM 模型被选择之前              |
| `before_prompt_build`      | `PluginHookBeforePromptBuildEvent`      | 系统/用户提示词被组装之前       |
| `before_agent_start`       | `PluginHookBeforeAgentStartEvent`       | Agent 运行开始之前              |
| `before_agent_reply`       | `PluginHookBeforeAgentReplyEvent`       | Agent 回复发送之前              |
| `llm_input`                | `PluginHookLlmInputEvent`               | LLM 输入准备好时                |
| `llm_output`               | `PluginHookLlmOutputEvent`              | 收到 LLM 输出时                 |
| `agent_end`                | `PluginHookAgentEndEvent`               | Agent 运行结束时                |
| `before_compaction`        | `PluginHookBeforeCompactionEvent`       | 会话压缩之前                    |
| `after_compaction`         | `PluginHookAfterCompactionEvent`        | 会话压缩之后                    |
| `before_reset`             | `PluginHookBeforeResetEvent`            | 会话重置之前                    |
| `inbound_claim`            | `PluginHookInboundClaimEvent`           | 用于申领入站消息                |
| `message_received`         | `PluginHookMessageReceivedEvent`        | 收到消息时                      |
| `message_sending`          | `PluginHookMessageSendingEvent`         | 消息被外部发送之前              |
| `message_sent`             | `PluginHookMessageSentEvent`            | 消息发送之后                    |
| `before_tool_call`         | `PluginHookBeforeToolCallEvent`         | 工具被调用之前（可以阻止/修改） |
| `after_tool_call`          | `PluginHookAfterToolCallEvent`          | 收到工具结果之后                |
| `tool_result_persist`      | `PluginHookToolResultPersistEvent`      | 工具结果被持久化时              |
| `before_message_write`     | `PluginHookBeforeMessageWriteEvent`     | 转录本消息被写入之前            |
| `session_start`            | `PluginHookSessionStartEvent`           | 会话开始时                      |
| `session_end`              | `PluginHookSessionEndEvent`             | 会话结束时                      |
| `subagent_spawning`        | `PluginHookSubagentSpawningEvent`       | 子 Agent 生成之前               |
| `subagent_delivery_target` | `PluginHookSubagentDeliveryTargetEvent` | 用于子 Agent 投递路由           |
| `subagent_spawned`         | `PluginHookSubagentSpawnedEvent`        | 子 Agent 生成之后               |
| `subagent_ended`           | `PluginHookSubagentEndedEvent`          | 子 Agent 结束时                 |
| `gateway_start`            | `PluginHookGatewayStartEvent`           | 网关启动时                      |
| `gateway_stop`             | `PluginHookGatewayStopEvent`            | 网关停止时                      |
| `before_dispatch`          | `PluginHookBeforeDispatchEvent`         | 消息分发之前                    |
| `reply_dispatch`           | `PluginHookReplyDispatchEvent`          | 回复消息时                      |
| `before_install`           | `PluginHookBeforeInstallEvent`          | 安装技能/插件之前               |

---

### 6. 插件/扩展如何接入事件

插件有三个**接入面**：

#### A. 插件钩子（高级生命周期钩子）
- **类型**：通过 `plugin.on(hookName, handler)` 注册的函数处理程序
- **覆盖范围**：29 个命名钩子，覆盖完整的 Agent 生命周期
- **入口**：`src/plugins/hooks.ts`（`HookRunner`）
- **类型**：`src/plugins/types.ts`
- **示例**：插件可以拦截 `before_tool_call` 以阻止或修改工具调用

#### B. Agent 事件（低级实时流）
- **类型**：订阅原始 `AgentEventPayload` 流
- **通过以下方式暴露**：`PluginRuntimeCore.events.onAgentEvent`
  - 定义于 `src/plugins/runtime/types-core.ts:101-103`
  - 实现于 `src/plugins/runtime/runtime-events.ts`
- **同时也提供**：用于转录本更改的 `onSessionTranscriptUpdate`
- **入口**：`src/infra/agent-events.ts` —— `onAgentEvent(listener)`
- **示例**：插件可以监听所有 Agent 生命周期事件、工具事件、助手流式文本

#### C. 钩子外部 HTTP Webhook
- **入口**：`src/gateway/hooks.ts`（HTTP 端点 `/hooks`）
- **配置**：配置文件中的 `hooks.enabled`、`hooks.token`、`hooks.mappings`
- **流程**：外部系统 POST 到 hooks 端点，然后转换为内部 Agent 会话
- **类型**：`src/gateway/hooks.types.ts`、`src/gateway/hooks-mapping.ts`

---

**7. 其他内部事件系统**

| 系统              | 文件                                       | 负载类型                                | 用途                          |
| :---------------- | :----------------------------------------- | :-------------------------------------- | :---------------------------- |
| 心跳事件          | `src/infra/heartbeat-events.ts`            | `HeartbeatEventPayload`                 | 跟踪心跳发送状态              |
| 诊断事件          | `src/infra/diagnostic-events.ts`           | `DiagnosticEventPayload`（13 种子类型） | 符合 OpenTelemetry 规范的诊断 |
| 系统事件          | `src/infra/system-events.ts`               | `SystemEvent`                           | 系统事件的临时队列            |
| 会话生命周期事件  | `src/sessions/session-lifecycle-events.ts` | `SessionLifecycleEvent`                 | 会话创建/删除                 |
| 转录本事件        | `src/sessions/transcript-events.ts`        | `SessionTranscriptUpdate`               | 转录本消息追加                |
| 内部 Agent 事件   | `src/agents/internal-events.ts`            | `AgentInternalEvent`                    | 子 Agent 任务完成             |
| 子 Agent 生命周期 | `src/agents/subagent-lifecycle-events.ts`  | 仅常量（无事件总线）                    | 子 Agent 生命周期结果         |

---

**8. 关键文件路径总结**

| 文件                                                     | 包含内容                                                     |
| :------------------------------------------------------- | :----------------------------------------------------------- |
| `src/infra/agent-events.ts`                              | 核心 Agent 事件总线——`emitAgentEvent()`、`onAgentEvent()`、类型 |
| `src/shared/listeners.ts`                                | 通用监听器原语——`registerListener()`、`notifyListeners()`    |
| `src/shared/global-singleton.ts`                         | 通过 `Symbol.for(...)` 解析全局单例                          |
| `src/gateway/server-runtime-subscriptions.ts`            | 事件连接——将 Agent 事件连接到网关广播                        |
| `src/gateway/server-chat.ts`                             | 聊天事件处理程序——桥接 Agent 事件到 WS 聊天事件              |
| `src/gateway/server-broadcast.ts`                        | WS 广播——`broadcast()`、`broadcastToConnIds()`               |
| `src/gateway/server-methods-list.ts`                     | 网关事件列表（`GATEWAY_EVENTS`）                             |
| `src/gateway/server-methods/chat.ts`                     | `Chat.send` 实现                                             |
| `src/gateway/server-session-events.ts`                   | 会话事件广播                                                 |
| `src/gateway/server.impl.ts`                             | 服务器连接——创建运行时状态，启动订阅                         |
| `src/gateway/server-runtime-state.ts`                    | 运行时状态——创建聊天运行状态、广播器                         |
| `src/gateway/protocol/schema/frames.ts`                  | WS 协议框架模式（`EventFrameSchema`）                        |
| `src/agents/pi-embedded-subscribe.handlers.lifecycle.ts` | Agent 生命周期事件发射（开始/结束/错误）                     |
| `src/agents/pi-embedded-subscribe.handlers.messages.ts`  | 助手流事件发射（文本增量）                                   |
| `src/agents/pi-embedded-subscribe.handlers.tools.ts`     | 工具事件发射（项目/命令/审批）                               |
| `src/agents/internal-event-contract.ts`                  | 内部事件类型常量                                             |
| `src/agents/internal-events.ts`                          | 内部事件（任务完成）                                         |
| `src/plugins/hooks.ts`                                   | 插件钩子运行程序                                             |
| `src/plugins/types.ts`                                   | 插件钩子类型定义（所有 29 个钩子）                           |
| `src/plugins/runtime/runtime-events.ts`                  | 插件运行时事件——暴露 `onAgentEvent`                          |
| `src/plugins/runtime/types-core.ts`                      | 插件运行时核心类型——`events.onAgentEvent`                    |
| `src/infra/heartbeat-events.ts`                          | 心跳事件系统                                                 |
| `src/infra/diagnostic-events.ts`                         | 诊断事件系统（13 种事件类型）                                |
| `src/infra/system-events.ts`                             | 系统事件队列                                                 |
| `src/sessions/session-lifecycle-events.ts`               | 会话生命周期事件                                             |
| `src/sessions/transcript-events.ts`                      | 转录本更新事件                                               |
| `src/tasks/task-registry.ts`                             | 任务注册表——使用 `onAgentEvent` 处理任务生命周期             |
| `src/gateway/hooks.ts`                                   | 外部 HTTP 钩子处理程序                                       |
| `src/hooks/types.ts`                                     | 钩子文件元数据类型（`hook.md` frontmatter）                  |