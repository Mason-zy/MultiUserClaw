from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.container.manager import ensure_running
from app.db.engine import async_session
from app.db.models import User
from app.runtime_backend import RuntimeContext
from app.runtime_backends.hermes_agents import (
    create_agent_profile_in_hermes_container,
    delete_agent_profile_from_hermes_container,
    get_agent_profile_file_from_hermes_container,
    list_agent_profile_files_from_hermes_container,
    set_agent_profile_file_in_hermes_container,
    update_agent_profile_in_hermes_container,
)
from app.runtime_backends.hermes_files import (
    browse_hermes_filemanager,
    delete_hermes_filemanager_path,
    make_hermes_filemanager_directory,
    normalize_hermes_filemanager_path,
    write_hermes_filemanager_file,
)
from app.runtime_backends.hermes_knowledge import (
    knowledge_graph,
    list_knowledge_pages,
    read_knowledge_page,
    search_knowledge_pages,
    write_knowledge_page,
)
from app.runtime_backends.hermes_skills import (
    delete_skill_from_hermes_container,
    install_existing_skill_to_hermes_scope,
    install_git_skills_to_hermes_container,
    list_skill_files_from_hermes_container,
    list_skills_from_hermes_container,
    read_skill_file_from_hermes_container,
    scan_git_skills,
    set_skill_disabled_in_hermes_container,
    skill_scopes,
    skill_zip_from_hermes_container,
    upload_skill_zip_to_hermes_container,
    write_skill_file_to_hermes_container,
)
from app.runtime_router import get_runtime_backend
from app.runtime_backends.skills_marketplace import load_recommended_skills, resolve_recommended_skill_dir

router = APIRouter(tags=["runtime-compat"])


class SessionTitleRequest(BaseModel):
    title: str


class SendMessageRequest(BaseModel):
    message: str
    model: str | None = None


class CreateAgentRequest(BaseModel):
    name: str
    displayName: str | None = None
    description: str | None = None
    workspace: str | None = None
    avatar: str | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    avatar: str | None = None


class WriteFileRequest(BaseModel):
    path: str | None = None
    content: str


class WriteKnowledgeRequest(BaseModel):
    path: str
    content: str
    agentId: str | None = None


class WriteAgentFileRequest(BaseModel):
    content: str


class TitleSummaryRequest(BaseModel):
    message: str = ""


class ApprovalRequest(BaseModel):
    choice: str
    resolveAll: bool = False


class SkillFileWriteRequest(BaseModel):
    scope: str = "global"
    agentId: str | None = None
    path: str
    content: str


class SkillToggleRequest(BaseModel):
    scope: str = "global"
    agentId: str | None = None
    disabled: bool


class SkillSearchRequest(BaseModel):
    query: str = ""
    limit: int = 10


class SkillInstallRequest(BaseModel):
    slug: str
    scope: str = "global"
    agentId: str | None = None


class GitScanRequest(BaseModel):
    url: str


class GitInstallRequest(BaseModel):
    cacheKey: str
    skillNames: list[str] = []
    scope: str = "global"
    agentId: str | None = None


class RecommendedSkillInstallRequest(BaseModel):
    category: str
    skillName: str


def _fallback_title(message: str) -> str | None:
    title = " ".join(message.strip().split())
    if not title:
        return None
    return title[:48]


@router.get("/api/openclaw/agents")
async def list_dedicated_agents(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.get_agent_info(RuntimeContext(user=user))


@router.post("/api/openclaw/agents")
async def create_dedicated_agent(
    req: CreateAgentRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return create_agent_profile_in_hermes_container(
        container.docker_id,
        req.name,
        display_name=req.displayName,
        description=req.description,
        avatar=req.avatar,
    )


@router.post("/api/openclaw/agents/icon")
async def generate_dedicated_agent_icon(
    req: dict,
    user: User = Depends(get_current_user),
):
    _ = user
    name = str(req.get("name") or "AI")
    seed = str(req.get("seed") or name)
    hue = abs(hash(seed)) % 360
    initials = "".join(part[:1] for part in name.split()[:2]).upper() or "AI"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
        f'<rect width="96" height="96" rx="24" fill="hsl({hue} 70% 45%)"/>'
        f'<text x="48" y="57" text-anchor="middle" font-size="28" font-family="Arial" '
        f'font-weight="700" fill="white">{initials}</text></svg>'
    )
    return {"ok": True, "svg": svg, "dataUrl": f"data:image/svg+xml;charset=UTF-8,{svg}"}


@router.get("/api/openclaw/agents/{agent_id}/files")
async def list_dedicated_agent_files(
    agent_id: str,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return list_agent_profile_files_from_hermes_container(container.docker_id, agent_id)


@router.put("/api/openclaw/agents/{agent_id}")
async def update_dedicated_agent(
    agent_id: str,
    req: UpdateAgentRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return update_agent_profile_in_hermes_container(container.docker_id, agent_id, name=req.name, avatar=req.avatar)


@router.delete("/api/openclaw/agents/{agent_id}")
async def delete_dedicated_agent(
    agent_id: str,
    delete_files: bool = False,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return delete_agent_profile_from_hermes_container(container.docker_id, agent_id, delete_files=delete_files)


@router.get("/api/openclaw/agents/{agent_id}/files/{name:path}")
async def get_dedicated_agent_file(
    agent_id: str,
    name: str,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return get_agent_profile_file_from_hermes_container(container.docker_id, agent_id, name)


@router.put("/api/openclaw/agents/{agent_id}/files/{name:path}")
async def set_dedicated_agent_file(
    agent_id: str,
    name: str,
    req: WriteAgentFileRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return set_agent_profile_file_in_hermes_container(container.docker_id, agent_id, name, req.content)


@router.get("/api/openclaw/skills")
async def list_dedicated_skills(
    all: bool = False,
    scope: str | None = None,
    agentId: str | None = None,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    if scope or all:
        async with async_session() as db:
            container = await ensure_running(db, user.id)
        if all and not scope:
            skills = list_skills_from_hermes_container(container.docker_id, scope="global")
            info = await backend.get_agent_info(RuntimeContext(user=user))
            agents = info.get("agents") if isinstance(info, dict) else []
            agent_ids = [str(item.get("id")) for item in agents if isinstance(item, dict) and item.get("id")]
            for resolved_agent_id in agent_ids:
                skills.extend(
                    list_skills_from_hermes_container(
                        container.docker_id,
                        scope="agent",
                        agent_id=resolved_agent_id,
                    )
                )
            return skills
        return list_skills_from_hermes_container(container.docker_id, scope=scope, agent_id=agentId)
    return await backend.list_skills(RuntimeContext(user=user))


@router.get("/api/openclaw/skills/scopes")
async def list_dedicated_skill_scopes(
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    info = await backend.get_agent_info(RuntimeContext(user=user))
    agents = info.get("agents") if isinstance(info, dict) else []
    agent_ids = [str(item.get("id")) for item in agents if isinstance(item, dict) and item.get("id")]
    return skill_scopes(agent_ids)


@router.delete("/api/openclaw/skills/{skill_name}")
async def delete_dedicated_skill(
    skill_name: str,
    scope: str | None = None,
    agentId: str | None = None,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return delete_skill_from_hermes_container(container.docker_id, skill_name, scope, agentId)


@router.put("/api/openclaw/skills/{skill_name}/disabled")
async def set_dedicated_skill_disabled(
    skill_name: str,
    req: SkillToggleRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return set_skill_disabled_in_hermes_container(container.docker_id, skill_name, req.disabled, req.scope, req.agentId)


@router.get("/api/openclaw/skills/{skill_name}/download")
async def download_dedicated_skill(
    skill_name: str,
    scope: str | None = None,
    agentId: str | None = None,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    content, media_type = skill_zip_from_hermes_container(container.docker_id, skill_name, scope, agentId)
    return Response(
        content=content,
        media_type=media_type,
        headers={"content-disposition": f'attachment; filename="{skill_name}.zip"'},
    )


@router.get("/api/openclaw/skills/{skill_name}/files")
async def list_dedicated_skill_files(
    skill_name: str,
    scope: str | None = None,
    agentId: str | None = None,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return list_skill_files_from_hermes_container(container.docker_id, skill_name, scope, agentId)


@router.get("/api/openclaw/skills/{skill_name}/files/content")
async def get_dedicated_skill_file(
    skill_name: str,
    path: str,
    scope: str | None = None,
    agentId: str | None = None,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return read_skill_file_from_hermes_container(container.docker_id, skill_name, path, scope, agentId)


@router.put("/api/openclaw/skills/{skill_name}/files/content")
async def write_dedicated_skill_file(
    skill_name: str,
    req: SkillFileWriteRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return write_skill_file_to_hermes_container(
        container.docker_id,
        skill_name,
        req.path,
        req.content,
        req.scope,
        req.agentId,
    )


@router.post("/api/openclaw/skills/upload")
async def upload_dedicated_skill_zip(
    file: UploadFile = File(...),
    scope: str = Form("global"),
    agentId: str | None = Form(None),
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return await upload_skill_zip_to_hermes_container(container.docker_id, file, scope, agentId)


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


@router.get("/api/openclaw/marketplaces/recommended")
async def list_recommended_skills(
    user: User = Depends(get_current_user),
):
    _ = user
    try:
        categories = load_recommended_skills()
    except Exception as exc:
        return {"categories": [], "error": str(exc)}
    return {"categories": categories}


@router.post("/api/openclaw/marketplaces/recommended/install")
async def install_recommended_skill(
    req: RecommendedSkillInstallRequest,
    user: User = Depends(get_current_user),
):
    from app.container.manager import get_docker_container
    from app.runtime_backends.hermes_skills import HERMES_SKILLS_ROOT, _build_skills_archive

    try:
        skill_dir = resolve_recommended_skill_dir(req.category, req.skillName)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}

    files: dict[str, bytes] = {}
    for file_path in skill_dir.rglob("*"):
        if file_path.is_file():
            rel = str(file_path.relative_to(skill_dir)).replace("\\", "/")
            files[rel] = file_path.read_bytes()

    archive = _build_skills_archive({req.skillName: files})
    async with async_session() as db:
        container_info = await ensure_running(db, user.id)
    container = get_docker_container(container_info.docker_id)
    container.exec_run(["mkdir", "-p", HERMES_SKILLS_ROOT])
    container.put_archive(HERMES_SKILLS_ROOT, archive)

    return {"ok": True, "name": req.skillName}


@router.post("/api/openclaw/marketplaces/skills/install")
async def install_dedicated_skill_from_search(
    req: SkillInstallRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return install_existing_skill_to_hermes_scope(container.docker_id, req.slug, req.scope, req.agentId)


@router.post("/api/openclaw/marketplaces/git/scan-skills")
async def scan_dedicated_git_skills(
    req: GitScanRequest,
    user: User = Depends(get_current_user),
):
    _ = user
    return scan_git_skills(req.url)


@router.post("/api/openclaw/marketplaces/git/install-skills")
async def install_dedicated_git_skills(
    req: GitInstallRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return install_git_skills_to_hermes_container(
        container.docker_id,
        req.cacheKey,
        req.skillNames,
        req.scope,
        req.agentId,
    )


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


@router.post("/api/openclaw/sessions/{session_key:path}/title-summary")
async def summarize_dedicated_session_title(
    session_key: str,
    req: TitleSummaryRequest,
    user: User = Depends(get_current_user),
):
    title = _fallback_title(req.message)
    backend = get_runtime_backend()
    if title:
        await backend.rename_session(RuntimeContext(user=user), session_key, title)
    return {"ok": True, "key": session_key, "title": title}


@router.post("/api/openclaw/sessions/{session_key:path}/messages")
async def send_dedicated_message(
    session_key: str,
    req: SendMessageRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    result = await backend.send_message(RuntimeContext(user=user), session_key, req.message, req.model)
    if isinstance(result, dict) and not result.get("title"):
        result["title"] = _fallback_title(req.message)
    return result


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


@router.post("/api/openclaw/runs/{run_id}/approval")
async def respond_dedicated_run_approval(
    run_id: str,
    req: ApprovalRequest,
    user: User = Depends(get_current_user),
):
    backend = get_runtime_backend()
    return await backend.respond_run_approval(
        RuntimeContext(user=user),
        run_id,
        req.choice,
        resolve_all=req.resolveAll,
    )


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


@router.get("/api/openclaw/knowledge/list")
async def list_dedicated_knowledge(
    agentId: str = "main",
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return list_knowledge_pages(container.docker_id, agentId)


@router.get("/api/openclaw/knowledge/read")
async def read_dedicated_knowledge(
    path: str,
    agentId: str = "main",
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return read_knowledge_page(container.docker_id, agentId, path)


@router.get("/api/openclaw/knowledge/search")
async def search_dedicated_knowledge(
    q: str = "",
    agentId: str = "main",
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return search_knowledge_pages(container.docker_id, agentId, q)


@router.get("/api/openclaw/knowledge/graph")
async def graph_dedicated_knowledge(
    agentId: str = "main",
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return knowledge_graph(container.docker_id, agentId)


@router.put("/api/openclaw/knowledge/write")
async def write_dedicated_knowledge(
    req: WriteKnowledgeRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return write_knowledge_page(container.docker_id, req.agentId or "main", req.path, req.content)


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


@router.put("/api/openclaw/filemanager/write")
async def write_dedicated_file(
    req: WriteFileRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        container = await ensure_running(db, user.id)
    return write_hermes_filemanager_file(container.docker_id, req.path, req.content)


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
