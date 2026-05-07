from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit_log
from app.config import settings
from app.db.models import ChatSession, SharedAgentBinding, User


@dataclass(slots=True)
class SharedAgentContext:
    binding: SharedAgentBinding
    session_prefix: str
    upload_dir: str


async def ensure_shared_mode_enabled() -> None:
    if not settings.shared_openclaw_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shared OpenClaw mode is disabled",
        )


async def require_shared_user(user: User) -> None:
    if user.runtime_mode != "shared":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not assigned to shared OpenClaw mode",
        )


async def shared_runtime_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    files: dict | None = None,
    timeout: float | None = None,
) -> object:
    await ensure_shared_mode_enabled()
    base_url = settings.shared_openclaw_url.rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shared OpenClaw URL is not configured",
        )

    effective_timeout = timeout or settings.shared_openclaw_timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            response = await client.request(
                method=method,
                url=f"{base_url}{path}",
                json=json,
                params=params,
                files=files,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Shared OpenClaw request failed: {exc}",
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise HTTPException(status_code=response.status_code, detail=detail or "Shared OpenClaw request failed")

    return payload


async def list_shared_agents() -> list[dict]:
    payload = await shared_runtime_request("GET", "/api/agents")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("agents"), list):
        return payload["agents"]
    return []


async def create_shared_agent(agent_id: str, workspace_dir: str, display_name: str | None = None) -> None:
    try:
        await shared_runtime_request(
            "POST",
            "/api/agents",
            json={
                "name": agent_id,
                "workspace": workspace_dir,
                "emoji": "🦀",
            },
        )
    except HTTPException as exc:
        detail_text = str(exc.detail).lower()
        if exc.status_code in {400, 409, 500} and any(token in detail_text for token in ("exists", "already", "duplicate")):
            return
        raise


def build_shared_agent_id(user_id: str) -> str:
    normalized = user_id.replace("-", "")
    return f"usr_{normalized[:24]}"


def build_session_key(agent_id: str) -> str:
    return f"agent:{agent_id}:session-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


def _extract_agent_id(session_key: str) -> str | None:
    """Parse agent_id from session_key (format: agent:<agent_id>:...)."""
    if not session_key or not session_key.startswith("agent:"):
        return None
    parts = session_key.split(":", 2)
    return parts[1] if len(parts) >= 2 else None


async def upsert_chat_session(
    db: AsyncSession,
    user_id: str,
    session_key: str,
    *,
    increment_message_count: bool = False,
) -> None:
    """Create or update a chat session record in the database."""
    from sqlalchemy import update

    agent_id = _extract_agent_id(session_key)

    # Try to find existing session
    result = await db.execute(
        select(ChatSession).where(ChatSession.session_key == session_key)
    )
    existing = result.scalar_one_or_none()

    if existing:
        if increment_message_count:
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == existing.id)
                .values(message_count=ChatSession.message_count + 1)
            )
        else:
            # Touch updated_at
            existing.updated_at = None  # triggers onupdate
    else:
        db.add(
            ChatSession(
                user_id=user_id,
                session_key=session_key,
                agent_id=agent_id,
            )
        )


async def ensure_shared_agent_binding(db: AsyncSession, user: User) -> SharedAgentContext:
    await ensure_shared_mode_enabled()
    await require_shared_user(user)

    result = await db.execute(
        select(SharedAgentBinding).where(SharedAgentBinding.user_id == user.id)
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        agent_id = build_shared_agent_id(user.id)
        workspace_dir = f"~/.openclaw/workspace-{agent_id}"
        await create_shared_agent(agent_id, workspace_dir, user.username)
        binding = SharedAgentBinding(
            user_id=user.id,
            openclaw_agent_id=agent_id,
            workspace_dir=workspace_dir,
            status="active",
        )
        db.add(binding)
        await write_audit_log(
            db,
            action="shared_agent_binding_create",
            user_id=user.id,
            resource=agent_id,
            detail={"workspace_dir": workspace_dir},
        )
        await db.commit()
        await db.refresh(binding)

    return SharedAgentContext(
        binding=binding,
        session_prefix=f"agent:{binding.openclaw_agent_id}:",
        upload_dir=f"workspace-{binding.openclaw_agent_id}/uploads",
    )


def ensure_session_owned(ctx: SharedAgentContext, session_key: str) -> str:
    normalized = (session_key or "").strip()
    if not normalized.startswith(ctx.session_prefix):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session does not belong to current user")
    return normalized


async def upload_file_to_shared_workspace(ctx: SharedAgentContext, file: UploadFile) -> dict:
    contents = await file.read()
    files = {
        "file": (file.filename or "upload.bin", contents, file.content_type or "application/octet-stream"),
        "path": (None, ctx.upload_dir),
    }
    payload = await shared_runtime_request("POST", "/api/filemanager/upload", files=files)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Unexpected upload response from shared OpenClaw")
    return payload
