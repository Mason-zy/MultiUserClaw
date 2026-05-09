import type { StreamFn } from "@mariozechner/pi-agent-core";
import { streamSimple } from "@mariozechner/pi-ai";
import { createAnthropicVertexStreamFnForModel } from "../anthropic-vertex-stream.js";
import { createOpenAIWebSocketStreamFn } from "../openai-ws-stream.js";
import { getModelProviderRequestTransport } from "../provider-request-config.js";
import { createBoundaryAwareStreamFnForModel } from "../provider-transport-stream.js";
import { stripSystemPromptCacheBoundary } from "../system-prompt-cache-boundary.js";
import type { EmbeddedRunAttemptParams } from "./run/types.js";

let embeddedAgentBaseStreamFnCache = new WeakMap<object, StreamFn | undefined>();

export function resolveEmbeddedAgentBaseStreamFn(params: {
  session: { agent: { streamFn?: StreamFn } };
}): StreamFn | undefined {
  const cached = embeddedAgentBaseStreamFnCache.get(params.session);
  if (cached !== undefined || embeddedAgentBaseStreamFnCache.has(params.session)) {
    return cached;
  }
  const baseStreamFn = params.session.agent.streamFn;
  embeddedAgentBaseStreamFnCache.set(params.session, baseStreamFn);
  return baseStreamFn;
}

export function resetEmbeddedAgentBaseStreamFnCacheForTest(): void {
  embeddedAgentBaseStreamFnCache = new WeakMap<object, StreamFn | undefined>();
}

export function describeEmbeddedAgentStreamStrategy(params: {
  currentStreamFn: StreamFn | undefined;
  providerStreamFn?: StreamFn;
  shouldUseWebSocketTransport: boolean;
  wsApiKey?: string;
  model: EmbeddedRunAttemptParams["model"];
}): string {
  if (params.providerStreamFn) {
    return "provider";
  }
  if (params.shouldUseWebSocketTransport) {
    return params.wsApiKey ? "openai-websocket" : "session-http-fallback";
  }
  if (params.model.provider === "anthropic-vertex") {
    return "anthropic-vertex";
  }
  return createBoundaryAwareStreamFnForModel(params.model)
    ? `boundary-aware:${params.model.api}`
    : `fallback:${params.model.api}`;
}

export async function resolveEmbeddedAgentApiKey(params: {
  provider: string;
  resolvedApiKey?: string;
  authStorage?: { getApiKey(provider: string): Promise<string | undefined> };
}): Promise<string | undefined> {
  const resolvedApiKey = params.resolvedApiKey?.trim();
  if (resolvedApiKey) {
    return resolvedApiKey;
  }
  return params.authStorage ? await params.authStorage.getApiKey(params.provider) : undefined;
}

export function resolveEmbeddedAgentStreamFn(params: {
  currentStreamFn: StreamFn | undefined;
  providerStreamFn?: StreamFn;
  shouldUseWebSocketTransport: boolean;
  wsApiKey?: string;
  sessionId: string;
  signal?: AbortSignal;
  model: EmbeddedRunAttemptParams["model"];
  resolvedApiKey?: string;
  authStorage?: { getApiKey(provider: string): Promise<string | undefined> };
}): StreamFn {
  // Resolve the inner stream function first.
  let inner: StreamFn;

  if (params.providerStreamFn) {
    const providerInner = params.providerStreamFn;
    const normalizeContext = (context: Parameters<StreamFn>[1]) =>
      context.systemPrompt
        ? {
            ...context,
            systemPrompt: stripSystemPromptCacheBoundary(context.systemPrompt),
          }
        : context;
    // Provider-owned transports bypass pi-coding-agent's default auth lookup,
    // so keep injecting the resolved runtime apiKey for streamSimple-compatible
    // transports that still read credentials from options.apiKey.
    if (params.authStorage || params.resolvedApiKey) {
      const { authStorage, model, resolvedApiKey } = params;
      inner = async (m, context, options) => {
        const apiKey = await resolveEmbeddedAgentApiKey({
          provider: model.provider,
          resolvedApiKey,
          authStorage,
        });
        return providerInner(m, normalizeContext(context), {
          ...options,
          apiKey: apiKey ?? options?.apiKey,
        });
      };
    } else {
      inner = (m, context, options) => providerInner(m, normalizeContext(context), options);
    }
  } else {
    const currentStreamFn = params.currentStreamFn ?? streamSimple;
    if (params.shouldUseWebSocketTransport) {
      inner = params.wsApiKey
        ? createOpenAIWebSocketStreamFn(params.wsApiKey, params.sessionId, {
            signal: params.signal,
            managerOptions: {
              request: getModelProviderRequestTransport(params.model),
            },
          })
        : currentStreamFn;
    } else if (params.model.provider === "anthropic-vertex") {
      inner = createAnthropicVertexStreamFnForModel(params.model);
    } else {
      // Always try the boundary-aware transport for supported APIs,
      // regardless of what currentStreamFn is. pi-agent-core may set a
      // non-streamSimple default that lacks session correlation headers.
      const boundaryAwareStreamFn = createBoundaryAwareStreamFnForModel(params.model);
      if (boundaryAwareStreamFn) {
        inner = boundaryAwareStreamFn;
      } else {
        const fnName = params.currentStreamFn?.name || "<anonymous>";
        const fnStr = String(params.currentStreamFn).slice(0, 200);
        console.log(
          "[stream-resolution] unsupported api — falling back to currentStreamFn name=%s preview=%s",
          fnName, fnStr,
        );
        inner = currentStreamFn;
      }
    }
  }

  // Inject sessionId and apiKey into options. pi-agent-core does not pass
  // sessionId in stream options, and may not pass the apiKey for non-native
  // providers (e.g. platform-proxy). We bridge both gaps here.
  const sessionId = params.sessionId;
  const resolvedApiKey = params.resolvedApiKey;
  const authStorage = params.authStorage;
  const model = params.model;

  if (resolvedApiKey || authStorage) {
    return async (m, context, options) => {
      const apiKey = await resolveEmbeddedAgentApiKey({
        provider: model.provider,
        resolvedApiKey,
        authStorage,
      });
      console.log(
        "[stream-resolution] invoking inner streamFn sessionId=%s apiKey=%s provider=%s api=%s",
        sessionId, apiKey ? "<set>" : "<none>", m.provider, m.api,
      );
      return inner(m, context, {
        ...options,
        sessionId,
        apiKey: apiKey ?? options?.apiKey,
      });
    };
  }

  return (m, context, options) => {
    console.log(
      "[stream-resolution] invoking inner streamFn sessionId=%s (no apiKey resolver) provider=%s api=%s",
      sessionId, m.provider, m.api,
    );
    return inner(m, context, { ...options, sessionId });
  };
}
