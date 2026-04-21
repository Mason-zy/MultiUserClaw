from __future__ import annotations

import json

import httpx
from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import decode_token, get_user_by_id
from app.config import settings
from app.db.engine import async_session
from app.db.models import User
from app.hermes_client import HermesClient
from app.runtime_backend import RuntimeBackend, RuntimeContext
from app.shared_runtime import (
    build_session_key,
    ensure_session_owned,
    ensure_shared_agent_binding,
    upload_file_to_shared_workspace,
)


class SharedHermesBackend(RuntimeBackend):
    async def _context_for_user(self, db: AsyncSession, user: User):
        return await ensure_shared_agent_binding(db, user)

    def _base_url(self) -> str:
        base_url = (settings.shared_hermes_url or settings.shared_openclaw_url).rstrip("/")
        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Shared Hermes URL is not configured",
            )
        return base_url

    def _client(self) -> HermesClient:
        return HermesClient(base_url=self._base_url(), timeout=settings.shared_openclaw_timeout_seconds)

    async def _request(self, method: str, path: str, **kwargs):
        return await self._client().request(method, path, **kwargs)

    def _session_summary(self, payload: dict) -> dict:
        message_count = payload.get("message_count")
        updated_at = payload.get("updated_at") or payload.get("last_message_at") or payload.get("created_at")
        return {
            "key": payload.get("session_id", ""),
            "sessionKey": payload.get("session_id", ""),
            "title": payload.get("title") or payload.get("session_id", ""),
            "updatedAt": updated_at,
            "messageCount": message_count if isinstance(message_count, int) else len(payload.get("messages") or []),
        }

    async def get_agent_info(self, ctx: RuntimeContext) -> dict:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        payload = await self._client().get_models()
        models = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(models, list):
            models = []
        if not models:
            models = [{"id": shared_ctx.binding.openclaw_agent_id, "object": "model"}]
        return {
            "agents": models,
            "defaultId": shared_ctx.binding.openclaw_agent_id,
            "runtime_mode": ctx.user.runtime_mode,
        }

    async def list_sessions(self, ctx: RuntimeContext) -> list[dict]:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        payload = await self._request("GET", "/api/hermes/sessions")
        sessions = payload.get("sessions") if isinstance(payload, dict) else []
        if not isinstance(sessions, list):
            return []
        return [
            self._session_summary(item)
            for item in sessions
            if isinstance(item, dict) and str(item.get("session_id", "")).startswith(shared_ctx.session_prefix)
        ]

    async def get_session(self, ctx: RuntimeContext, session_key: str):
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key)
        payload = await self._request("GET", f"/api/hermes/sessions/{key}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Unexpected Hermes session response")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = []
        return {
            "key": payload.get("session_id", key),
            "sessionKey": payload.get("session_id", key),
            "title": payload.get("title") or payload.get("session_id", key),
            "messages": messages,
            "messageCount": payload.get("message_count", len(messages)),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at") or payload.get("last_message_at") or payload.get("created_at"),
        }

    async def send_message(self, ctx: RuntimeContext, session_key: str, message: str) -> dict:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key) if session_key else build_session_key(shared_ctx.binding.openclaw_agent_id)
        payload = await self._client().create_run(message=message, session_id=key)
        return {
            "ok": True,
            "run_id": payload.get("run_id", "") if isinstance(payload, dict) else "",
            "runId": payload.get("run_id", "") if isinstance(payload, dict) else "",
            "session_key": payload.get("session_id", key) if isinstance(payload, dict) else key,
            "sessionKey": payload.get("session_id", key) if isinstance(payload, dict) else key,
            "raw": payload if isinstance(payload, dict) else {},
        }

    async def wait_run(self, ctx: RuntimeContext, run_id: str, timeout_ms: int):
        events = await self._client().collect_run_events(run_id, timeout_ms=timeout_ms)
        final_message = {}
        status_text = "pending"
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "message.completed" and isinstance(event.get("message"), dict):
                final_message = event["message"]
            if event_type == "run.completed":
                status_text = "completed"
            elif event_type == "run.failed":
                status_text = "failed"
        return {
            "run_id": run_id,
            "status": status_text,
            "message": final_message,
            "events": events,
        }

    async def rename_session(self, ctx: RuntimeContext, session_key: str, title: str):
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key)
        payload = await self._request("PUT", f"/api/hermes/sessions/{key}/title", json={"title": title})
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "session_key": key, "title": title}

    async def delete_session(self, ctx: RuntimeContext, session_key: str):
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key)
        payload = await self._request("DELETE", f"/api/hermes/sessions/{key}")
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "session_key": key}

    async def upload_file(self, ctx: RuntimeContext, file: UploadFile) -> dict:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        return await upload_file_to_shared_workspace(shared_ctx, file)

    def _map_event_to_compat_block(self, event: dict) -> str | None:
        event_type = str(event.get("type", ""))
        session_key = event.get("session_id") or event.get("session_key")
        payload: dict

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
            shared_ctx = await self._context_for_user(db, user)

        target_url = f"{self._base_url()}/api/hermes/events/stream"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url) as resp:
                        if resp.status_code >= 400:
                            yield b'data: {"error":"shared hermes upstream error"}\n\n'
                            return
                        buffer = ""
                        async for chunk in resp.aiter_text():
                            if await request.is_disconnected():
                                break
                            buffer += chunk
                            while "\n\n" in buffer:
                                block, buffer = buffer.split("\n\n", 1)
                                for line in block.splitlines():
                                    if not line.startswith("data:"):
                                        continue
                                    raw = line[5:].strip()
                                    if raw == "[DONE]":
                                        continue
                                    try:
                                        event = json.loads(raw)
                                    except json.JSONDecodeError:
                                        continue
                                    if not isinstance(event, dict):
                                        continue
                                    session_key = event.get("session_id") or event.get("session_key")
                                    if session_key and str(session_key).startswith(shared_ctx.session_prefix):
                                        mapped = self._map_event_to_compat_block(event)
                                        if mapped:
                                            yield mapped.encode("utf-8")
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"error":"shared hermes upstream disconnected"}\n\n'

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
            await self._context_for_user(db, user)

        target_url = f"{self._base_url()}/v1/runs/{run_id}/events"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url) as resp:
                        if resp.status_code >= 400:
                            yield b'data: {"event":"run.failed","error":"shared hermes upstream error"}\n\n'
                            return
                        async for chunk in resp.aiter_bytes():
                            if await request.is_disconnected():
                                break
                            yield chunk
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"event":"run.failed","error":"shared hermes upstream disconnected"}\n\n'

        return StreamingResponse(
            _stream_sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
