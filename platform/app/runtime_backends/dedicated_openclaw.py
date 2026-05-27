from __future__ import annotations

import asyncio

import httpx
from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.auth.service import decode_token, get_user_by_id
from app.config import settings
from app.container.manager import ensure_running
from app.db.engine import async_session
from app.runtime_backend import RuntimeBackend, RuntimeContext


class DedicatedOpenClawBackend(RuntimeBackend):
    async def _base_url(self, ctx: RuntimeContext) -> str:
        if settings.dev_openclaw_url:
            return settings.dev_openclaw_url
        async with async_session() as db:
            container = await ensure_running(db, ctx.user.id)
        return f"http://{container.internal_host}:{container.internal_port}"

    async def _request(self, ctx: RuntimeContext, method: str, path: str, **kwargs):
        base_url = await self._base_url(ctx)
        timeout = kwargs.pop("timeout", 120.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.request(method=method, url=f"{base_url}{path}", **kwargs)
            except httpx.ConnectError as exc:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenClaw container is starting up") from exc
            except httpx.TimeoutException as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Dedicated OpenClaw request timed out",
                ) from exc
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Dedicated OpenClaw runtime is unavailable",
                ) from exc

        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text

        if resp.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise HTTPException(status_code=resp.status_code, detail=detail or "Dedicated OpenClaw request failed")
        return payload

    async def prewarm(self, ctx: RuntimeContext) -> dict:
        await self._base_url(ctx)
        attempts = max(1, settings.hermes_connect_retries)
        delay_seconds = max(0.0, settings.hermes_retry_delay_seconds)
        last_exc: HTTPException | None = None
        for attempt in range(attempts):
            try:
                await self._request(ctx, "GET", "/api/agents", timeout=2.0)
                return {"ok": True, "status": "ready", "runtime": "openclaw"}
            except HTTPException as exc:
                last_exc = exc
                if exc.status_code < 500 or attempt == attempts - 1:
                    raise
                if delay_seconds:
                    await asyncio.sleep(delay_seconds)
        if last_exc is not None:
            raise last_exc
        return {"ok": True, "status": "ready", "runtime": "openclaw"}

    async def get_agent_info(self, ctx: RuntimeContext) -> dict:
        payload = await self._request(ctx, "GET", "/api/agents")
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return {"agents": payload}
        return {"agents": []}

    async def list_skills(self, ctx: RuntimeContext) -> list[dict]:
        payload = await self._request(ctx, "GET", "/api/skills")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("skills"), list):
            return [item for item in payload["skills"] if isinstance(item, dict)]
        return []

    async def list_sessions(self, ctx: RuntimeContext) -> list[dict]:
        payload = await self._request(ctx, "GET", "/api/sessions")
        return payload if isinstance(payload, list) else []

    async def get_session(self, ctx: RuntimeContext, session_key: str):
        return await self._request(ctx, "GET", f"/api/sessions/{session_key}")

    async def send_message(self, ctx: RuntimeContext, session_key: str, message: str) -> dict:
        payload = await self._request(ctx, "POST", f"/api/sessions/{session_key}/messages", json={"message": message}, timeout=300.0)
        return payload if isinstance(payload, dict) else {}

    async def wait_run(self, ctx: RuntimeContext, run_id: str, timeout_ms: int):
        return await self._request(ctx, "GET", f"/api/runs/{run_id}/wait", params={"timeoutMs": timeout_ms}, timeout=(timeout_ms / 1000) + 5)

    async def rename_session(self, ctx: RuntimeContext, session_key: str, title: str):
        return await self._request(ctx, "PUT", f"/api/sessions/{session_key}/title", json={"title": title})

    async def delete_session(self, ctx: RuntimeContext, session_key: str):
        return await self._request(ctx, "DELETE", f"/api/sessions/{session_key}")

    async def abort_run(self, ctx: RuntimeContext, run_id: str, session_key: str = "") -> dict:
        try:
            payload = await self._request(ctx, "POST", f"/api/runs/{run_id}/abort", json={"sessionKey": session_key})
            return payload if isinstance(payload, dict) else {"ok": True, "aborted": True, "runIds": [run_id]}
        except Exception:
            return {"ok": False, "aborted": False, "runIds": []}

    async def abort_active_session(self, ctx: RuntimeContext, session_key: str) -> dict:
        try:
            payload = await self._request(ctx, "POST", f"/api/sessions/{session_key}/abort-active")
            return payload if isinstance(payload, dict) else {"ok": True, "aborted": True, "runIds": []}
        except Exception:
            return {"ok": False, "aborted": False, "runIds": []}

    async def list_commands(self, ctx: RuntimeContext, agent_id: str = "") -> dict:
        try:
            payload = await self._request(ctx, "GET", "/api/commands", params={"agentId": agent_id} if agent_id else None)
            return payload if isinstance(payload, dict) else {"agentId": agent_id, "commands": []}
        except Exception:
            return {"agentId": agent_id, "commands": []}

    async def upload_file(
        self,
        ctx: RuntimeContext,
        file: UploadFile,
        target_dir: str | None = None,
    ) -> dict:
        contents = await file.read()
        files = {
            "file": (
                file.filename or "upload.bin",
                contents,
                file.content_type or "application/octet-stream",
            )
        }
        if target_dir:
            files["path"] = (None, target_dir)
        payload = await self._request(
            ctx,
            "POST",
            "/api/filemanager/upload",
            files=files,
        )
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Unexpected upload response from dedicated OpenClaw")
        return payload

    async def stream_events(self, ctx: RuntimeContext, request: Request, token: str):
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        async with async_session() as db:
            user = await get_user_by_id(db, payload["sub"])
            if user is None or not user.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not found")
            stream_ctx = RuntimeContext(user=user)
            base_url = await self._base_url(stream_ctx)

        target_url = f"{base_url}/api/events/stream"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"error":"upstream disconnected"}\n\n'

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
            base_url = await self._base_url(stream_ctx)

        target_url = f"{base_url}/api/runs/{run_id}/events"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url) as resp:
                        async for chunk in resp.aiter_bytes():
                            if await request.is_disconnected():
                                break
                            yield chunk
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"error":"upstream disconnected"}\n\n'

        return StreamingResponse(
            _stream_sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
