from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.container.manager import ensure_running
from app.db.engine import async_session
from app.db.models import User
from app.runtime_backend import RuntimeContext
from app.runtime_backends.hermes_files import (
    browse_hermes_filemanager,
    delete_hermes_filemanager_path,
    make_hermes_filemanager_directory,
    normalize_hermes_filemanager_path,
)
from app.runtime_backends.hermes_skills import list_skills_from_hermes_container, upload_skill_zip_to_hermes_container
from app.runtime_router import get_runtime_backend

router = APIRouter(tags=["runtime-compat"])


class SessionTitleRequest(BaseModel):
    title: str


class SendMessageRequest(BaseModel):
    message: str


class SkillSearchRequest(BaseModel):
    query: str = ""
    limit: int = 10


@router.get("/api/openclaw/agents")
async def list_dedicated_agents(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.get_agent_info(RuntimeContext(user=user))


@router.get("/api/openclaw/skills")
async def list_dedicated_skills(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.list_skills(RuntimeContext(user=user))


@router.post("/api/openclaw/skills/upload")
async def upload_dedicated_skill_zip(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return await upload_skill_zip_to_hermes_container(container.docker_id, file)


@router.post("/api/openclaw/marketplaces/skills/search")
async def search_dedicated_skills(
    req: SkillSearchRequest,
    user: User = Depends(get_current_user),
):
    query = req.query.strip().lower()
    limit = max(1, min(req.limit or 10, 50))
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    skills = list_skills_from_hermes_container(container.docker_id)

    results = []
    for skill in skills:
        path = str(skill.get("path") or skill.get("name") or "")
        haystack = " ".join(
            str(skill.get(key) or "") for key in ("name", "description", "source", "path")
        ).lower()
        if query and query not in haystack:
            continue
        results.append(
            {
                "slug": str(skill.get("name") or path),
                "url": f"local://{path}",
                "installs": "installed",
                "description": str(skill.get("description") or ""),
                "source": str(skill.get("source") or "hermes"),
                "path": path,
            }
        )
        if len(results) >= limit:
            break
    return {"results": results, "runtime": "hermes"}


@router.post("/api/openclaw/runtime/prewarm")
async def prewarm_dedicated_runtime(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.prewarm(RuntimeContext(user=user))


@router.get("/api/openclaw/sessions")
async def list_dedicated_sessions(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.list_sessions(RuntimeContext(user=user))


@router.get("/api/openclaw/sessions/{session_key:path}")
async def get_dedicated_session(
    session_key: str,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.get_session(RuntimeContext(user=user), session_key)


@router.post("/api/openclaw/sessions/{session_key:path}/messages")
async def send_dedicated_message(
    session_key: str,
    req: SendMessageRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.send_message(RuntimeContext(user=user), session_key, req.message)


@router.get("/api/openclaw/runs/{run_id}/wait")
async def wait_dedicated_run(
    run_id: str,
    timeout_ms: Annotated[int, Query(alias="timeoutMs")] = 25000,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.wait_run(RuntimeContext(user=user), run_id, timeout_ms)


@router.get("/api/openclaw/runs/{run_id}/events")
async def dedicated_run_events_stream(
    run_id: str,
    request: Request,
    token: str = "",
):
    user = User(id="", username="", email="", password_hash="")
    backend = get_runtime_backend()
    return await backend.stream_run_events(RuntimeContext(user=user), request, token, run_id)


@router.put("/api/openclaw/sessions/{session_key:path}/title")
async def rename_dedicated_session(
    session_key: str,
    req: SessionTitleRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.rename_session(RuntimeContext(user=user), session_key, req.title)


@router.delete("/api/openclaw/sessions/{session_key:path}")
async def delete_dedicated_session(
    session_key: str,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.delete_session(RuntimeContext(user=user), session_key)


class AbortRunRequest(BaseModel):
    sessionKey: str = ""


@router.post("/api/openclaw/runs/{run_id}/abort")
async def abort_dedicated_run(
    run_id: str,
    req: AbortRunRequest | None = None,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    session_key = req.sessionKey if req else ""
    return await backend.abort_run(RuntimeContext(user=user), run_id, session_key)


@router.post("/api/openclaw/sessions/{session_key:path}/abort-active")
async def abort_dedicated_active_session(
    session_key: str,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.abort_active_session(RuntimeContext(user=user), session_key)


@router.get("/api/openclaw/commands")
async def list_dedicated_commands(
    agentId: str = "",
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.list_commands(RuntimeContext(user=user), agentId)


@router.post("/api/openclaw/filemanager/upload")
@router.post("/api/openclaw/files/upload")
async def upload_dedicated_file(
    file: UploadFile = File(...),
    path: str | None = Form(None),
    upload_dir: str | None = Form(None),
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.upload_file(
        RuntimeContext(user=user),
        file,
        target_dir=normalize_hermes_filemanager_path(path or upload_dir),
    )


@router.get("/api/openclaw/filemanager/browse")
async def browse_dedicated_files(
    path: str = "",
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return browse_hermes_filemanager(container.docker_id, path)


@router.post("/api/openclaw/filemanager/mkdir")
async def mkdir_dedicated_file(
    path: str = Query(...),
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return make_hermes_filemanager_directory(container.docker_id, path)


@router.delete("/api/openclaw/filemanager/delete")
async def delete_dedicated_file(
    path: str = Query(...),
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return delete_hermes_filemanager_path(container.docker_id, path)


@router.get("/api/openclaw/events/stream")
async def dedicated_events_stream(
    request: Request,
    token: str = "",
):
    # user is recovered inside backend from token for EventSource compatibility
    user = User(id="", username="", email="", password_hash="")
    backend = get_runtime_backend()
    return await backend.stream_events(RuntimeContext(user=user), request, token)
