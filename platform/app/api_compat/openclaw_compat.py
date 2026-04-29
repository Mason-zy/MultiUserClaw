from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.engine import get_db
from app.db.models import User
from app.runtime_backend import RuntimeContext
from app.runtime_router import get_runtime_backend

router = APIRouter(tags=["runtime-compat"])


class SessionTitleRequest(BaseModel):
    title: str


class SendMessageRequest(BaseModel):
    message: str


class SharedChatRequest(BaseModel):
    message: str
    session_key: str | None = None


@router.get("/api/openclaw/agents")
async def list_dedicated_agents(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.get_agent_info(RuntimeContext(user=user, scope="dedicated"))


@router.get("/api/openclaw/skills")
async def list_dedicated_skills(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.list_skills(RuntimeContext(user=user, scope="dedicated"))


@router.get("/api/openclaw/sessions")
async def list_dedicated_sessions(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.list_sessions(RuntimeContext(user=user, scope="dedicated"))


@router.get("/api/openclaw/sessions/{session_key:path}")
async def get_dedicated_session(
    session_key: str,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.get_session(RuntimeContext(user=user, scope="dedicated"), session_key)


@router.post("/api/openclaw/sessions/{session_key:path}/messages")
async def send_dedicated_message(
    session_key: str,
    req: SendMessageRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.send_message(RuntimeContext(user=user, scope="dedicated"), session_key, req.message)


@router.get("/api/openclaw/runs/{run_id}/wait")
async def wait_dedicated_run(
    run_id: str,
    timeout_ms: Annotated[int, Query(alias="timeoutMs")] = 25000,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.wait_run(RuntimeContext(user=user, scope="dedicated"), run_id, timeout_ms)


@router.get("/api/openclaw/runs/{run_id}/events")
async def dedicated_run_events_stream(
    run_id: str,
    request: Request,
    token: str = "",
):
    user = User(id="", username="", email="", password_hash="", runtime_mode="dedicated")
    backend = get_runtime_backend(user)
    return await backend.stream_run_events(RuntimeContext(user=user, scope="dedicated"), request, token, run_id)


@router.put("/api/openclaw/sessions/{session_key:path}/title")
async def rename_dedicated_session(
    session_key: str,
    req: SessionTitleRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.rename_session(RuntimeContext(user=user, scope="dedicated"), session_key, req.title)


@router.delete("/api/openclaw/sessions/{session_key:path}")
async def delete_dedicated_session(
    session_key: str,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.delete_session(RuntimeContext(user=user, scope="dedicated"), session_key)


@router.post("/api/openclaw/filemanager/upload")
@router.post("/api/openclaw/files/upload")
async def upload_dedicated_file(
    file: UploadFile = File(...),
    path: str | None = Form(None),
    upload_dir: str | None = Form(None),
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.upload_file(
        RuntimeContext(user=user, scope="dedicated"),
        file,
        target_dir=path or upload_dir,
    )


@router.get("/api/openclaw/events/stream")
async def dedicated_events_stream(
    request: Request,
    token: str = "",
):
    # user is recovered inside backend from token for EventSource compatibility
    user = User(id="", username="", email="", password_hash="", runtime_mode="dedicated")
    backend = get_runtime_backend(user)
    return await backend.stream_events(RuntimeContext(user=user, scope="dedicated"), request, token)


@router.get("/api/shared-openclaw/me")
async def get_shared_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = db
    backend = get_runtime_backend(user)
    return await backend.get_agent_info(RuntimeContext(user=user, scope="shared"))


@router.get("/api/shared-openclaw/sessions")
async def list_shared_sessions(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.list_sessions(RuntimeContext(user=user, scope="shared"))


@router.get("/api/shared-openclaw/sessions/{session_key:path}")
async def get_shared_session(
    session_key: str,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.get_session(RuntimeContext(user=user, scope="shared"), session_key)


@router.post("/api/shared-openclaw/chat")
async def send_shared_chat(
    req: SharedChatRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.send_message(RuntimeContext(user=user, scope="shared"), req.session_key or "", req.message)


@router.get("/api/shared-openclaw/runs/{run_id}/wait")
async def wait_shared_run(
    run_id: str,
    timeout_ms: Annotated[int, Query(alias="timeoutMs")] = 25000,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.wait_run(RuntimeContext(user=user, scope="shared"), run_id, timeout_ms)


@router.get("/api/shared-openclaw/runs/{run_id}/events")
async def shared_run_events_stream(
    run_id: str,
    request: Request,
    token: str = "",
):
    user = User(id="", username="", email="", password_hash="", runtime_mode="shared")
    backend = get_runtime_backend(user)
    return await backend.stream_run_events(RuntimeContext(user=user, scope="shared"), request, token, run_id)


@router.put("/api/shared-openclaw/sessions/{session_key:path}/title")
async def rename_shared_session(
    session_key: str,
    req: SessionTitleRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.rename_session(RuntimeContext(user=user, scope="shared"), session_key, req.title)


@router.delete("/api/shared-openclaw/sessions/{session_key:path}")
async def delete_shared_session(
    session_key: str,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.delete_session(RuntimeContext(user=user, scope="shared"), session_key)


@router.post("/api/shared-openclaw/files/upload")
async def upload_shared_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend(user)
    return await backend.upload_file(RuntimeContext(user=user, scope="shared"), file)


@router.get("/api/shared-openclaw/events/stream")
async def shared_events_stream(
    request: Request,
    token: str = "",
):
    user = User(id="", username="", email="", password_hash="", runtime_mode="shared")
    backend = get_runtime_backend(user)
    return await backend.stream_events(RuntimeContext(user=user, scope="shared"), request, token)
