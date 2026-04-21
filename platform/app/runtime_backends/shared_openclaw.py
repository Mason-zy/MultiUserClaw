from __future__ import annotations

import json

import httpx
from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import decode_token, get_user_by_id
from app.db.engine import async_session
from app.db.models import User
from app.runtime_backend import RuntimeBackend, RuntimeContext
from app.shared_runtime import (
    build_session_key,
    ensure_session_owned,
    ensure_shared_agent_binding,
    shared_runtime_request,
    upload_file_to_shared_workspace,
)


class SharedOpenClawBackend(RuntimeBackend):
    async def _context_for_user(self, db: AsyncSession, user: User):
        return await ensure_shared_agent_binding(db, user)

    async def get_agent_info(self, ctx: RuntimeContext) -> dict:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        return {
            "runtime_mode": ctx.user.runtime_mode,
            "agent_id": shared_ctx.binding.openclaw_agent_id,
            "workspace_dir": shared_ctx.binding.workspace_dir,
            "upload_dir": shared_ctx.upload_dir,
            "username": ctx.user.username,
            "status": shared_ctx.binding.status,
        }

    async def list_sessions(self, ctx: RuntimeContext) -> list[dict]:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        payload = await shared_runtime_request("GET", "/api/sessions")
        sessions = payload if isinstance(payload, list) else []
        return [item for item in sessions if isinstance(item, dict) and str(item.get("key", "")).startswith(shared_ctx.session_prefix)]

    async def get_session(self, ctx: RuntimeContext, session_key: str):
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key)
        return await shared_runtime_request("GET", f"/api/sessions/{key}")

    async def send_message(self, ctx: RuntimeContext, session_key: str, message: str) -> dict:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key) if session_key else build_session_key(shared_ctx.binding.openclaw_agent_id)
        payload = await shared_runtime_request(
            "POST",
            f"/api/sessions/{key}/messages",
            json={"message": message},
            timeout=300,
        )
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("session_key", key)
        return payload

    async def wait_run(self, ctx: RuntimeContext, run_id: str, timeout_ms: int):
        return await shared_runtime_request("GET", f"/api/runs/{run_id}/wait", params={"timeoutMs": timeout_ms}, timeout=(timeout_ms / 1000) + 5)

    async def rename_session(self, ctx: RuntimeContext, session_key: str, title: str):
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key)
        return await shared_runtime_request("PUT", f"/api/sessions/{key}/title", json={"title": title})

    async def delete_session(self, ctx: RuntimeContext, session_key: str):
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        key = ensure_session_owned(shared_ctx, session_key)
        return await shared_runtime_request("DELETE", f"/api/sessions/{key}")

    async def upload_file(self, ctx: RuntimeContext, file: UploadFile) -> dict:
        async with async_session() as db:
            shared_ctx = await self._context_for_user(db, ctx.user)
        return await upload_file_to_shared_workspace(shared_ctx, file)

    def _filter_shared_sse_block(self, block: str, session_prefix: str) -> str | None:
        normalized = block.replace("\r\n", "\n").strip("\n")
        if not normalized:
            return None
        if normalized.startswith(":"):
            return normalized

        data_lines = [line[5:].lstrip() for line in normalized.split("\n") if line.startswith("data:")]
        if not data_lines:
            return None

        payload_text = "\n".join(data_lines).strip()
        try:
            envelope = json.loads(payload_text)
        except json.JSONDecodeError:
            return None

        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        session_key = None
        if isinstance(payload, dict):
            session_key = payload.get("sessionKey") or payload.get("session_key")

        if session_key and str(session_key).startswith(session_prefix):
            return normalized
        return None

    async def stream_events(self, ctx: RuntimeContext, request: Request, token: str):
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        async with async_session() as db:
            user = await get_user_by_id(db, payload["sub"])
            if user is None or not user.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not found")
            shared_ctx = await self._context_for_user(db, user)

        from app.config import settings
        target_url = f"{settings.shared_openclaw_url.rstrip('/')}/api/events/stream"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url) as resp:
                        buffer = ""
                        async for chunk in resp.aiter_text():
                            if await request.is_disconnected():
                                break
                            buffer += chunk
                            while "\n\n" in buffer:
                                block, buffer = buffer.split("\n\n", 1)
                                filtered = self._filter_shared_sse_block(block, shared_ctx.session_prefix)
                                if filtered:
                                    yield (filtered + "\n\n").encode("utf-8")
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"error":"shared upstream disconnected"}\n\n'

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

        from app.config import settings
        target_url = f"{settings.shared_openclaw_url.rstrip('/')}/api/runs/{run_id}/events"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url) as resp:
                        async for chunk in resp.aiter_bytes():
                            if await request.is_disconnected():
                                break
                            yield chunk
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"error":"shared upstream disconnected"}\n\n'

        return StreamingResponse(
            _stream_sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
