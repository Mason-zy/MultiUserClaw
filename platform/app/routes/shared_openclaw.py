from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.service import decode_token, get_user_by_id
from app.config import settings
from app.db.engine import async_session, get_db
from app.db.models import User
from app.shared_runtime import (
    build_session_key,
    ensure_session_owned,
    ensure_shared_agent_binding,
    shared_runtime_request,
    upsert_chat_session,
    upload_file_to_shared_workspace,
)

router = APIRouter(prefix="/api/shared-openclaw", tags=["shared-openclaw"])


class SharedAgentInfo(BaseModel):
    runtime_mode: str
    agent_id: str
    workspace_dir: str
    upload_dir: str
    username: str
    status: str


class SharedChatRequest(BaseModel):
    message: str
    session_key: str | None = None


class SharedChatResponse(BaseModel):
    ok: bool
    runId: str | None = None
    session_key: str


class SessionTitleRequest(BaseModel):
    title: str


def _filter_shared_sse_block(block: str, session_prefix: str) -> str | None:
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


@router.get("/events/stream")
async def shared_events_stream(
    request: Request,
    token: str = "",
):
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    async with async_session() as db:
        user = await get_user_by_id(db, payload["sub"])
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not found")
        ctx = await ensure_shared_agent_binding(db, user)

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
                            filtered = _filter_shared_sse_block(block, ctx.session_prefix)
                            if filtered:
                                yield (filtered + "\n\n").encode("utf-8")
            except (httpx.ConnectError, httpx.RemoteProtocolError):
                yield b'data: {"error":"shared upstream disconnected"}\n\n'

    return StreamingResponse(
        _stream_sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/me", response_model=SharedAgentInfo)
async def get_shared_agent_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ensure_shared_agent_binding(db, user)
    return SharedAgentInfo(
        runtime_mode=user.runtime_mode,
        agent_id=ctx.binding.openclaw_agent_id,
        workspace_dir=ctx.binding.workspace_dir,
        upload_dir=ctx.upload_dir,
        username=user.username,
        status=ctx.binding.status,
    )


@router.get("/sessions")
async def list_shared_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ensure_shared_agent_binding(db, user)
    payload = await shared_runtime_request("GET", "/api/sessions")
    sessions = payload if isinstance(payload, list) else []
    return [item for item in sessions if isinstance(item, dict) and str(item.get("key", "")).startswith(ctx.session_prefix)]


@router.get("/sessions/{session_key:path}")
async def get_shared_session(
    session_key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ensure_shared_agent_binding(db, user)
    key = ensure_session_owned(ctx, session_key)
    return await shared_runtime_request("GET", f"/api/sessions/{key}")


@router.post("/chat", response_model=SharedChatResponse)
async def send_shared_chat(
    req: SharedChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ensure_shared_agent_binding(db, user)
    session_key = ensure_session_owned(ctx, req.session_key) if req.session_key else build_session_key(ctx.binding.openclaw_agent_id)
    await upsert_chat_session(db, user.id, session_key, increment_message_count=bool(req.session_key))
    await db.commit()
    payload = await shared_runtime_request(
        "POST",
        f"/api/sessions/{session_key}/messages",
        json={"message": req.message},
        timeout=300,
    )
    if not isinstance(payload, dict):
        payload = {}
    return SharedChatResponse(ok=True, runId=payload.get("runId"), session_key=session_key)


@router.get("/runs/{run_id}/wait")
async def wait_shared_run(
    run_id: str,
    timeoutMs: int = 25000,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_shared_agent_binding(db, user)
    return await shared_runtime_request("GET", f"/api/runs/{run_id}/wait", params={"timeoutMs": timeoutMs}, timeout=(timeoutMs / 1000) + 5)


@router.put("/sessions/{session_key:path}/title")
async def rename_shared_session(
    session_key: str,
    req: SessionTitleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ensure_shared_agent_binding(db, user)
    key = ensure_session_owned(ctx, session_key)
    return await shared_runtime_request("PUT", f"/api/sessions/{key}/title", json={"title": req.title})


@router.delete("/sessions/{session_key:path}")
async def delete_shared_session(
    session_key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ensure_shared_agent_binding(db, user)
    key = ensure_session_owned(ctx, session_key)
    return await shared_runtime_request("DELETE", f"/api/sessions/{key}")


@router.post("/runs/{run_id}/abort")
async def abort_shared_run(
    run_id: str,
    session_key: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Abort a specific run (stop model inference)."""
    await ensure_shared_agent_binding(db, user)
    payload = {"sessionKey": session_key} if session_key else {}
    return await shared_runtime_request("POST", f"/api/runs/{run_id}/abort", json=payload)


@router.post("/sessions/{session_key:path}/abort-active")
async def abort_active_shared_session_run(
    session_key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Abort the active run in a session."""
    ctx = await ensure_shared_agent_binding(db, user)
    key = ensure_session_owned(ctx, session_key)
    return await shared_runtime_request("POST", f"/api/sessions/{key}/abort-active")


@router.post("/files/upload")
async def upload_shared_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ensure_shared_agent_binding(db, user)
    return await upload_file_to_shared_workspace(ctx, file)
