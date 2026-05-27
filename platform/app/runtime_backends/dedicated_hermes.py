from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.auth.service import decode_token, get_user_by_id
from app.config import settings
from app.container.manager import ensure_running
from app.db.engine import async_session
from app.hermes_client import HermesClient
from app.runtime_backend import RuntimeContext
from app.runtime_backends.hermes_files import (
    DEFAULT_HERMES_UPLOAD_DIR,
    read_data_file_from_hermes_container,
    write_upload_to_hermes_container,
)
from app.runtime_backends.hermes_agents import build_agent_info, model_for_session_key
from app.runtime_backends.hermes_run import (
    HermesEventSanitizer,
    HermesRunTimingTracker,
    format_latency_ms,
    sanitize_hermes_message,
    sanitize_hermes_messages,
    sanitize_run_events,
    sanitize_sse_block,
    summarize_run_events,
)
from app.runtime_backends.hermes_skills import list_skills_from_hermes_container

logger = logging.getLogger(__name__)

LEGACY_OPENCLAW_SESSIONS_INDEX = "agents/main/sessions/sessions.json"


def _is_generated_openclaw_session_key(session_key: str) -> bool:
    return session_key.startswith("agent:") and ":session-" in session_key


def _empty_openclaw_session(session_key: str) -> dict[str, Any]:
    return {
        "key": session_key,
        "sessionKey": session_key,
        "title": session_key.rsplit(":", 1)[-1] or session_key,
        "messages": [],
        "messageCount": 0,
        "createdAt": None,
        "updatedAt": None,
        "runtime": "hermes",
        "pending": True,
    }


def _legacy_ms_to_iso(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, str) and value:
        return value
    return None


def _clean_legacy_openclaw_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("Sender (untrusted metadata):") and "\n\n[" in cleaned:
        cleaned = "[" + cleaned.rsplit("\n\n[", 1)[1]
    if cleaned.startswith("["):
        close = cleaned.find("] ")
        if 0 <= close < 120:
            cleaned = cleaned[close + 2 :]
    return cleaned.strip()


def _legacy_openclaw_message_content(content: Any) -> str:
    if isinstance(content, str):
        return _clean_legacy_openclaw_text(content)
    if not isinstance(content, list):
        return ""
    text_parts = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            text_parts.append(text)
    return _clean_legacy_openclaw_text("\n".join(text_parts))


def _legacy_openclaw_session_id(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    session_id = record.get("sessionId")
    if isinstance(session_id, str) and session_id:
        return session_id
    session_file = record.get("sessionFile")
    if isinstance(session_file, str) and session_file.endswith(".jsonl"):
        return session_file.rsplit("/", 1)[-1].removesuffix(".jsonl")
    return ""


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


class DedicatedHermesBackend:
    def __init__(self, base_url: str | None = None):
        self._base_url_override = base_url
        self._api_ready_keys: set[tuple[str, str]] = set()
        self._api_ready_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._clients: dict[tuple[str, str, int, float], HermesClient] = {}

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def _wait_for_api_ready(
        self,
        ctx: RuntimeContext,
        base_url: str,
        runtime_id: str = "",
    ) -> None:
        ready_key = (base_url, runtime_id)
        if ready_key in self._api_ready_keys:
            return
        lock = self._api_ready_locks.setdefault(ready_key, asyncio.Lock())
        async with lock:
            if ready_key in self._api_ready_keys:
                return
            started_at = time.perf_counter()
            client = HermesClient(
                base_url=base_url,
                api_key=settings.dedicated_hermes_api_key,
                connect_retries=settings.hermes_connect_retries,
                retry_delay_seconds=settings.hermes_retry_delay_seconds,
            )
            await client.get_models()
            self._api_ready_keys.add(ready_key)
            logger.info(
                "hermes_api_ready scope=%s user_id=%s elapsed_ms=%.1f base_url=%s runtime_id=%s",
                "dedicated",
                ctx.user.id,
                _elapsed_ms(started_at),
                base_url,
                runtime_id,
            )

    async def _resolve_base_url(self, ctx: RuntimeContext) -> str:
        if self._base_url_override:
            return self._base_url_override.rstrip("/")
        if settings.dev_openclaw_url:
            return settings.dev_openclaw_url.rstrip("/")
        started_at = time.perf_counter()
        async with async_session() as db:
            container = await ensure_running(db, ctx.user.id)
        if not container.internal_host or not container.internal_port:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hermes runtime address is unavailable",
            )
        logger.info(
            "hermes_runtime_ready scope=%s user_id=%s elapsed_ms=%.1f host=%s port=%s",
            "dedicated",
            ctx.user.id,
            _elapsed_ms(started_at),
            container.internal_host,
            container.internal_port,
        )
        base_url = f"http://{container.internal_host}:{container.internal_port}"
        runtime_id = str(getattr(container, "docker_id", "") or "")
        await self._wait_for_api_ready(ctx, base_url, runtime_id)
        return base_url

    async def _client(self, ctx: RuntimeContext) -> HermesClient:
        base_url = await self._resolve_base_url(ctx)
        key = (
            base_url,
            settings.dedicated_hermes_api_key,
            settings.hermes_connect_retries,
            settings.hermes_retry_delay_seconds,
        )
        client = self._clients.get(key)
        if client is None:
            client = HermesClient(
                base_url=base_url,
                api_key=settings.dedicated_hermes_api_key,
                connect_retries=settings.hermes_connect_retries,
                retry_delay_seconds=settings.hermes_retry_delay_seconds,
            )
            self._clients[key] = client
        return client

    async def _request(self, ctx: RuntimeContext, method: str, path: str, **kwargs) -> Any:
        client = await self._client(ctx)
        return await client.request(method, path, **kwargs)

    async def prewarm(self, ctx: RuntimeContext) -> dict:
        await self._resolve_base_url(ctx)
        return {"ok": True, "status": "ready", "runtime": "hermes"}

    async def _session_record(self, ctx: RuntimeContext, session_key: str) -> dict[str, Any]:
        payload = await self._request(ctx, "GET", f"/api/hermes/sessions/{session_key}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Unexpected Hermes session response")
        return payload

    def _session_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        message_count = payload.get("message_count")
        updated_at = payload.get("updated_at") or payload.get("last_message_at") or payload.get("created_at")
        return {
            "key": payload.get("session_id", ""),
            "sessionKey": payload.get("session_id", ""),
            "title": payload.get("title") or payload.get("session_id", ""),
            "updatedAt": updated_at,
            "messageCount": message_count if isinstance(message_count, int) else len(payload.get("messages") or []),
        }

    async def _read_legacy_data_file(self, ctx: RuntimeContext, path: str) -> str:
        async with async_session() as db:
            container = await ensure_running(db, ctx.user.id)
        data = read_data_file_from_hermes_container(container.docker_id, path)
        return data.decode("utf-8")

    async def _legacy_openclaw_session_index(self, ctx: RuntimeContext) -> dict[str, Any]:
        try:
            raw = await self._read_legacy_data_file(ctx, LEGACY_OPENCLAW_SESSIONS_INDEX)
            payload = json.loads(raw)
        except Exception as exc:
            logger.debug("legacy_openclaw_sessions_unavailable user_id=%s error=%s", ctx.user.id, exc)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _legacy_openclaw_session_summary(self, session_key: str, record: Any) -> dict[str, Any] | None:
        if not isinstance(record, dict) or not _legacy_openclaw_session_id(record):
            return None
        updated_at = _legacy_ms_to_iso(record.get("updatedAt"))
        created_at = _legacy_ms_to_iso(record.get("createdAt"))
        return {
            "key": session_key,
            "sessionKey": session_key,
            "title": str(record.get("title") or session_key),
            "created_at": created_at,
            "createdAt": created_at,
            "updated_at": updated_at,
            "updatedAt": updated_at,
            "messageCount": record.get("messageCount") if isinstance(record.get("messageCount"), int) else None,
            "runtime": "legacy-openclaw",
            "readonly": True,
        }

    def _legacy_openclaw_messages_from_jsonl(self, raw: str) -> tuple[list[dict[str, Any]], str | None]:
        messages = []
        created_at = None
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            timestamp = event.get("timestamp")
            if created_at is None:
                created_at = _legacy_ms_to_iso(timestamp)
            if event.get("type") != "message":
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").strip()
            content = _legacy_openclaw_message_content(message.get("content"))
            if role not in {"user", "assistant", "system", "tool"} or not content:
                continue
            messages.append(
                {
                    "role": role,
                    "content": content,
                    "timestamp": _legacy_ms_to_iso(message.get("timestamp")) or _legacy_ms_to_iso(timestamp),
                }
            )
        return messages, created_at

    async def _legacy_openclaw_session(self, ctx: RuntimeContext, session_key: str) -> dict[str, Any] | None:
        index = await self._legacy_openclaw_session_index(ctx)
        record = index.get(session_key)
        session_id = _legacy_openclaw_session_id(record)
        if not session_id:
            return None
        try:
            raw = await self._read_legacy_data_file(ctx, f"agents/main/sessions/{session_id}.jsonl")
        except Exception as exc:
            logger.debug("legacy_openclaw_session_file_unavailable user_id=%s session_key=%s error=%s", ctx.user.id, session_key, exc)
            raw = ""
        messages, created_at = self._legacy_openclaw_messages_from_jsonl(raw)
        updated_at = _legacy_ms_to_iso(record.get("updatedAt")) if isinstance(record, dict) else None
        return {
            "key": session_key,
            "sessionKey": session_key,
            "title": str(record.get("title") or session_key) if isinstance(record, dict) else session_key,
            "messages": messages,
            "messageCount": len(messages),
            "created_at": created_at,
            "createdAt": created_at,
            "updated_at": updated_at,
            "updatedAt": updated_at,
            "runtime": "legacy-openclaw",
            "readonly": True,
        }

    async def get_agent_info(self, ctx: RuntimeContext) -> dict:
        payload = await (await self._client(ctx)).get_models()
        models = payload.get("data") if isinstance(payload, dict) else []
        return build_agent_info(
            models if isinstance(models, list) else [],
        )

    async def list_skills(self, ctx: RuntimeContext) -> list[dict]:
        async with async_session() as db:
            container = await ensure_running(db, ctx.user.id)
        return list_skills_from_hermes_container(container.docker_id)

    async def list_sessions(self, ctx: RuntimeContext) -> list[dict]:
        payload = await self._request(ctx, "GET", "/api/hermes/sessions")
        sessions = payload.get("sessions") if isinstance(payload, dict) else []
        if not isinstance(sessions, list):
            sessions = []
        summaries = [self._session_summary(item) for item in sessions if isinstance(item, dict)]
        seen_keys = {str(item.get("key") or item.get("sessionKey") or "") for item in summaries}
        legacy_index = await self._legacy_openclaw_session_index(ctx)
        for session_key, record in legacy_index.items():
            if not isinstance(session_key, str) or session_key in seen_keys:
                continue
            summary = self._legacy_openclaw_session_summary(session_key, record)
            if summary is not None:
                summaries.append(summary)
        return summaries

    async def get_session(self, ctx: RuntimeContext, session_key: str):
        try:
            payload = await self._session_record(ctx, session_key)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            legacy = await self._legacy_openclaw_session(ctx, session_key)
            if legacy is not None:
                return legacy
            if _is_generated_openclaw_session_key(session_key):
                return _empty_openclaw_session(session_key)
            raise
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = []
        messages = sanitize_hermes_messages(messages)
        return {
            "key": payload.get("session_id", session_key),
            "sessionKey": payload.get("session_id", session_key),
            "title": payload.get("title") or payload.get("session_id", session_key),
            "messages": messages,
            "messageCount": payload.get("message_count", len(messages)),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at") or payload.get("last_message_at") or payload.get("created_at"),
        }

    def _conversation_history_from_messages(self, messages: list[Any]) -> list[dict[str, str]]:
        history = []
        for item in sanitize_hermes_messages(messages):
            role = str(item.get("role") or "").strip()
            content = item.get("content")
            if role not in {"user", "assistant", "system"} or not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue
            history.append({"role": role, "content": content})
        return history

    async def _conversation_history(self, ctx: RuntimeContext, session_key: str) -> list[dict[str, str]]:
        if not session_key:
            return []
        try:
            payload = await self._session_record(ctx, session_key)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                logger.debug(
                    "hermes_session_history_unavailable scope=%s user_id=%s session_key=%s status=%s",
                    "dedicated",
                    ctx.user.id,
                    session_key,
                    exc.status_code,
                )
            return []
        except Exception as exc:
            logger.debug(
                "hermes_session_history_unavailable scope=%s user_id=%s session_key=%s error=%s",
                "dedicated",
                ctx.user.id,
                session_key,
                exc,
            )
            return []
        messages = payload.get("messages") if isinstance(payload, dict) else []
        return self._conversation_history_from_messages(messages if isinstance(messages, list) else [])

    async def send_message(self, ctx: RuntimeContext, session_key: str, message: str) -> dict:
        started_at = time.perf_counter()
        conversation_history = await self._conversation_history(ctx, session_key)
        payload = await (await self._client(ctx)).create_run(
            message=message,
            session_id=session_key or None,
            session_key=session_key or None,
            model=model_for_session_key(session_key),
            conversation_history=conversation_history,
        )
        run_id = payload.get("run_id") if isinstance(payload, dict) else None
        effective_session_key = payload.get("session_id") if isinstance(payload, dict) else None
        logger.info(
            "hermes_run_started scope=%s user_id=%s session_key=%s run_id=%s elapsed_ms=%.1f",
            "dedicated",
            ctx.user.id,
            effective_session_key or session_key,
            run_id or "",
            _elapsed_ms(started_at),
        )
        return {
            "ok": True,
            "run_id": run_id or "",
            "runId": run_id or "",
            "session_key": effective_session_key or session_key,
            "sessionKey": effective_session_key or session_key,
            "raw": payload if isinstance(payload, dict) else {},
        }

    async def wait_run(self, ctx: RuntimeContext, run_id: str, timeout_ms: int):
        started_at = time.perf_counter()
        timing = HermesRunTimingTracker(lambda: _elapsed_ms(started_at))

        events = await (await self._client(ctx)).collect_run_events(
            run_id,
            timeout_ms=timeout_ms,
            on_event=timing.record,
        )
        events = sanitize_run_events(events)
        status_text, final_message = summarize_run_events(events)
        logger.info(
            "hermes_run_finished scope=%s user_id=%s run_id=%s status=%s first_event_ms=%s first_delta_ms=%s first_visible_delta_ms=%s elapsed_ms=%.1f event_count=%d",
            "dedicated",
            ctx.user.id,
            run_id,
            status_text,
            format_latency_ms(timing.first_event_ms),
            format_latency_ms(timing.first_delta_ms),
            format_latency_ms(timing.first_visible_delta_ms),
            _elapsed_ms(started_at),
            len(events),
        )
        return {
            "run_id": run_id,
            "status": status_text,
            "message": final_message,
            "events": events,
        }

    async def rename_session(self, ctx: RuntimeContext, session_key: str, title: str):
        payload = await self._request(ctx, "PUT", f"/api/hermes/sessions/{session_key}/title", json={"title": title})
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "session_key": session_key, "title": title}

    async def delete_session(self, ctx: RuntimeContext, session_key: str):
        payload = await self._request(ctx, "DELETE", f"/api/hermes/sessions/{session_key}")
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "session_key": session_key}

    async def abort_run(self, ctx: RuntimeContext, run_id: str, session_key: str = "") -> dict:
        """Stop a running agent via POST /v1/runs/{run_id}/stop."""
        try:
            payload = await (await self._client(ctx)).request(
                "POST", f"/v1/runs/{run_id}/stop", timeout=10.0,
            )
            return {
                "ok": True,
                "aborted": True,
                "runIds": [run_id],
            }
        except Exception as exc:
            logger.warning("abort_run failed run_id=%s: %s", run_id, exc)
            return {"ok": False, "aborted": False, "runIds": []}

    async def abort_active_session(self, ctx: RuntimeContext, session_key: str) -> dict:
        """Best-effort abort: no direct hermes API for session-level abort."""
        return {"ok": True, "aborted": False, "runIds": []}

    async def list_commands(self, ctx: RuntimeContext, agent_id: str = "") -> dict:
        """Build slash command list from skills installed in the user's container."""
        from app.runtime_backends.hermes_skills import list_skills_from_hermes_container

        # Built-in gateway commands useful in the web UI
        builtin: list[dict] = [
            {"name": "new", "description": "开始新会话", "argument_hint": None, "aliases": [], "category": "session", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "retry", "description": "重试上一条消息", "argument_hint": None, "aliases": [], "category": "session", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "undo", "description": "撤销上一轮对话", "argument_hint": None, "aliases": [], "category": "session", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "title", "description": "设置会话标题", "argument_hint": "[name]", "aliases": [], "category": "session", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "model", "description": "切换模型", "argument_hint": "[model]", "aliases": [], "category": "options", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "help", "description": "显示帮助信息", "argument_hint": None, "aliases": [], "category": "status", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "status", "description": "显示会话状态", "argument_hint": None, "aliases": [], "category": "status", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "skills", "description": "管理技能", "argument_hint": "[list|search|install]", "aliases": [], "category": "tools", "scope": "both", "source": "builtin", "skill_name": None},
            {"name": "stop", "description": "停止所有后台进程", "argument_hint": None, "aliases": [], "category": "session", "scope": "both", "source": "builtin", "skill_name": None},
        ]

        # Skill-based slash commands from the user's hermes container
        skill_commands: list[dict] = []
        try:
            async with async_session() as db:
                container = await ensure_running(db, ctx.user.id)
            skills = list_skills_from_hermes_container(container.docker_id)
            for skill in skills:
                name = str(skill.get("name", ""))
                if not name:
                    continue
                cmd_name = name.lower().replace("_", "-").replace(" ", "-")
                skill_commands.append({
                    "name": cmd_name,
                    "description": str(skill.get("description", "")),
                    "argument_hint": "<prompt>",
                    "aliases": [],
                    "category": "skills",
                    "scope": "both",
                    "source": "skill",
                    "skill_name": name,
                })
        except Exception:
            pass

        return {"agentId": agent_id or "innovation", "commands": builtin + skill_commands}

    async def upload_file(
        self,
        ctx: RuntimeContext,
        file: UploadFile,
        target_dir: str | None = None,
    ) -> dict:
        async with async_session() as db:
            container = await ensure_running(db, ctx.user.id)

        payload = await write_upload_to_hermes_container(
            container.docker_id,
            file,
            target_dir or DEFAULT_HERMES_UPLOAD_DIR,
        )
        payload["url"] = f"/api/openclaw/filemanager/serve?path=/{payload['path']}"
        return payload

    def _map_event_to_compat_block(self, event: dict[str, Any]) -> str | None:
        event_type = str(event.get("type", ""))
        session_key = event.get("session_id") or event.get("session_key")
        payload: dict[str, Any]

        if event_type == "message.delta":
            delta = event.get("delta")
            if not delta:
                return None
            payload = {
                "event": "chat",
                "payload": {
                    "state": "delta",
                    "sessionKey": session_key,
                    "message": {"content": delta},
                },
            }
        elif event_type == "message.completed":
            message = event.get("message")
            if not isinstance(message, dict):
                return None
            message = sanitize_hermes_message(message)
            payload = {
                "event": "chat",
                "payload": {
                    "state": "final",
                    "sessionKey": session_key,
                    "message": message,
                },
            }
        elif event_type == "run.failed":
            payload = {
                "event": "chat",
                "payload": {
                    "state": "error",
                    "sessionKey": session_key,
                    "detail": event.get("error") or event.get("message") or "run failed",
                },
            }
        else:
            return None
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def stream_events(self, ctx: RuntimeContext, request: Request, token: str):
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        async with async_session() as db:
            user = await get_user_by_id(db, payload["sub"])
            if user is None or not user.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not found")

        stream_ctx = RuntimeContext(user=user)
        base_url = await self._resolve_base_url(stream_ctx)
        target_url = f"{base_url}/api/hermes/events/stream"
        headers = {}
        if settings.dedicated_hermes_api_key:
            headers["Authorization"] = f"Bearer {settings.dedicated_hermes_api_key}"

        async def _stream_sse():
            sanitizer = HermesEventSanitizer()
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url, headers=headers) as resp:
                        if resp.status_code >= 400:
                            yield b'data: {"error":"dedicated hermes upstream error"}\n\n'
                            return
                        buffer = ""
                        async for chunk in resp.aiter_text():
                            if await request.is_disconnected():
                                break
                            buffer += chunk
                            while "\n\n" in buffer:
                                block, buffer = buffer.split("\n\n", 1)
                                data_lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
                                if not data_lines:
                                    continue
                                try:
                                    event = json.loads("\n".join(data_lines))
                                except json.JSONDecodeError:
                                    continue
                                if not isinstance(event, dict):
                                    continue
                                event = sanitizer.sanitize_event(event)
                                if event is None:
                                    continue
                                mapped = self._map_event_to_compat_block(event)
                                if mapped:
                                    yield mapped.encode("utf-8")
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"error":"dedicated hermes upstream disconnected"}\n\n'

        return StreamingResponse(
            _stream_sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def stream_run_events(self, ctx: RuntimeContext, request: Request, token: str, run_id: str):
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        async with async_session() as db:
            user = await get_user_by_id(db, payload["sub"])
            if user is None or not user.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not found")

        stream_ctx = RuntimeContext(user=user)
        target_url = f"{await self._resolve_base_url(stream_ctx)}/v1/runs/{run_id}/events"
        headers = {}
        if settings.dedicated_hermes_api_key:
            headers["Authorization"] = f"Bearer {settings.dedicated_hermes_api_key}"

        async def _stream_sse():
            sanitizer = HermesEventSanitizer()
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url, headers=headers) as resp:
                        if resp.status_code >= 400:
                            yield b'data: {"event":"run.failed","error":"dedicated hermes upstream error"}\n\n'
                            return
                        buffer = ""
                        async for chunk in resp.aiter_bytes():
                            if await request.is_disconnected():
                                break
                            buffer += chunk.decode("utf-8", errors="ignore")
                            while "\n\n" in buffer:
                                block, buffer = buffer.split("\n\n", 1)
                                sanitized = sanitize_sse_block(block, sanitizer)
                                if sanitized:
                                    yield sanitized.encode("utf-8")
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"event":"run.failed","error":"dedicated hermes upstream disconnected"}\n\n'

        return StreamingResponse(
            _stream_sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
