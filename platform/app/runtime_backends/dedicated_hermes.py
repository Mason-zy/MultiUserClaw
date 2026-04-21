from __future__ import annotations

import io
import json
import tarfile
import time
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


class DedicatedHermesBackend:
    def __init__(self, base_url: str | None = None):
        self._base_url_override = base_url

    async def _resolve_base_url(self, ctx: RuntimeContext) -> str:
        if self._base_url_override:
            return self._base_url_override.rstrip("/")
        if settings.dev_openclaw_url:
            return settings.dev_openclaw_url.rstrip("/")
        async with async_session() as db:
            container = await ensure_running(db, ctx.user.id)
        if not container.internal_host or not container.internal_port:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hermes runtime address is unavailable",
            )
        return f"http://{container.internal_host}:{container.internal_port}"

    async def _client(self, ctx: RuntimeContext) -> HermesClient:
        return HermesClient(
            base_url=await self._resolve_base_url(ctx),
            api_key=settings.dedicated_hermes_api_key,
        )

    async def _request(self, ctx: RuntimeContext, method: str, path: str, **kwargs) -> Any:
        client = await self._client(ctx)
        return await client.request(method, path, **kwargs)

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

    async def get_agent_info(self, ctx: RuntimeContext) -> dict:
        payload = await (await self._client(ctx)).get_models()
        models = payload.get("data") if isinstance(payload, dict) else []
        return {"agents": models if isinstance(models, list) else []}

    async def list_sessions(self, ctx: RuntimeContext) -> list[dict]:
        payload = await self._request(ctx, "GET", "/api/hermes/sessions")
        sessions = payload.get("sessions") if isinstance(payload, dict) else []
        if not isinstance(sessions, list):
            return []
        return [self._session_summary(item) for item in sessions if isinstance(item, dict)]

    async def get_session(self, ctx: RuntimeContext, session_key: str):
        payload = await self._session_record(ctx, session_key)
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = []
        return {
            "key": payload.get("session_id", session_key),
            "sessionKey": payload.get("session_id", session_key),
            "title": payload.get("title") or payload.get("session_id", session_key),
            "messages": messages,
            "messageCount": payload.get("message_count", len(messages)),
            "createdAt": payload.get("created_at"),
            "updatedAt": payload.get("updated_at") or payload.get("last_message_at") or payload.get("created_at"),
        }

    async def send_message(self, ctx: RuntimeContext, session_key: str, message: str) -> dict:
        payload = await (await self._client(ctx)).create_run(message=message, session_id=session_key or None)
        run_id = payload.get("run_id") if isinstance(payload, dict) else None
        effective_session_key = payload.get("session_id") if isinstance(payload, dict) else None
        return {
            "ok": True,
            "run_id": run_id or "",
            "runId": run_id or "",
            "session_key": effective_session_key or session_key,
            "sessionKey": effective_session_key or session_key,
            "raw": payload if isinstance(payload, dict) else {},
        }

    async def wait_run(self, ctx: RuntimeContext, run_id: str, timeout_ms: int):
        events = await (await self._client(ctx)).collect_run_events(run_id, timeout_ms=timeout_ms)
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
        payload = await self._request(ctx, "PUT", f"/api/hermes/sessions/{session_key}/title", json={"title": title})
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "session_key": session_key, "title": title}

    async def delete_session(self, ctx: RuntimeContext, session_key: str):
        payload = await self._request(ctx, "DELETE", f"/api/hermes/sessions/{session_key}")
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "session_key": session_key}

    async def upload_file(self, ctx: RuntimeContext, file: UploadFile) -> dict:
        async with async_session() as db:
            container = await ensure_running(db, ctx.user.id)

        contents = await file.read()
        filename = file.filename or "upload.bin"
        stored_name = f"{int(time.time() * 1000)}-{filename}"
        relative_path = f"workspace/uploads/{stored_name}"

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            uploads_dir = tarfile.TarInfo(name="workspace/uploads")
            uploads_dir.type = tarfile.DIRTYPE
            uploads_dir.mode = 0o755
            uploads_dir.mtime = int(time.time())
            tar.addfile(uploads_dir)

            upload_file = tarfile.TarInfo(name=relative_path)
            upload_file.size = len(contents)
            upload_file.mode = 0o644
            upload_file.mtime = int(time.time())
            tar.addfile(upload_file, io.BytesIO(contents))

        tar_buffer.seek(0)
        ok = container.put_archive("/", tar_buffer.read())
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to write upload into Hermes workspace")

        return {
            "path": f"/workspace/uploads/{stored_name}",
            "name": stored_name,
            "original_name": filename,
            "size": len(contents),
            "content_type": file.content_type or "application/octet-stream",
            "url": f"/api/openclaw/filemanager/serve?path=/workspace/uploads/{stored_name}",
        }

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

        stream_ctx = RuntimeContext(user=user, scope=ctx.scope)
        base_url = await self._resolve_base_url(stream_ctx)
        target_url = f"{base_url}/api/hermes/events/stream"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url) as resp:
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

        stream_ctx = RuntimeContext(user=user, scope=ctx.scope)
        target_url = f"{await self._resolve_base_url(stream_ctx)}/v1/runs/{run_id}/events"
        headers = {}
        if settings.dedicated_hermes_api_key:
            headers["Authorization"] = f"Bearer {settings.dedicated_hermes_api_key}"

        async def _stream_sse():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("GET", target_url, headers=headers) as resp:
                        if resp.status_code >= 400:
                            yield b'data: {"event":"run.failed","error":"dedicated hermes upstream error"}\n\n'
                            return
                        async for chunk in resp.aiter_bytes():
                            if await request.is_disconnected():
                                break
                            yield chunk
                except (httpx.ConnectError, httpx.RemoteProtocolError):
                    yield b'data: {"event":"run.failed","error":"dedicated hermes upstream disconnected"}\n\n'

        return StreamingResponse(
            _stream_sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
