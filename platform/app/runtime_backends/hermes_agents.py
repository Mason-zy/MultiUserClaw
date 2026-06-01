from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

DEFAULT_HERMES_MODEL = "hermes-agent"
CONTAINER_PROFILES_DIR = "/opt/data/profiles"

_SESSION_AGENT_RE = re.compile(r"^agent:([^:]+):")
_IDENTITY_NAME_RE = re.compile(r"(?:\*\*)?\s*(?:名字|name)\s*(?:：|:)\s*(?:\*\*)?\s*(.+)", re.IGNORECASE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _deploy_copy_dir() -> Path:
    existing_candidates: list[Path] = []
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "deploy_copy"
        if (candidate / "openclaw_defaults.json").is_file() or (candidate / "Agents").is_dir():
            return candidate
        if candidate.exists():
            existing_candidates.append(candidate)
    if existing_candidates:
        return existing_candidates[0]
    return _repo_root() / "deploy_copy"


def _defaults_path() -> Path:
    return _deploy_copy_dir() / "openclaw_defaults.json"


def _agents_dir() -> Path:
    return _deploy_copy_dir() / "Agents"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _agent_ids_from_defaults(defaults: dict[str, Any]) -> list[str]:
    agents = defaults.get("agents")
    if not isinstance(agents, dict):
        return []
    agent_list = agents.get("list")
    if not isinstance(agent_list, list):
        return []
    ids: list[str] = []
    for item in agent_list:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        if agent_id and agent_id not in ids:
            ids.append(agent_id)
    return ids


def _agent_config_by_id(defaults: dict[str, Any]) -> dict[str, dict[str, Any]]:
    agents = defaults.get("agents")
    if not isinstance(agents, dict):
        return {}
    agent_list = agents.get("list")
    if not isinstance(agent_list, list):
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in agent_list:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        if agent_id:
            by_id[agent_id] = item
    return by_id


def _agent_dirs() -> list[str]:
    root = _agents_dir()
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and entry.name and not entry.name.startswith(".")
    )


def _identity_name(agent_id: str) -> str:
    identity = _agents_dir() / agent_id / "IDENTITY.md"
    try:
        lines = identity.read_text(encoding="utf-8").splitlines()
    except OSError:
        return agent_id

    for line in lines:
        match = _IDENTITY_NAME_RE.search(line)
        if match:
            value = match.group(1).strip().strip("*").strip()
            if value:
                return value
    return agent_id


def _agent_description(agent_id: str) -> str:
    identity = _agents_dir() / agent_id / "IDENTITY.md"
    try:
        text = identity.read_text(encoding="utf-8")
    except OSError:
        return ""
    marker = "## 一句话简介"
    if marker not in text:
        return ""
    tail = text.split(marker, 1)[1].strip()
    return next((line.strip() for line in tail.splitlines() if line.strip()), "")


def _resolve_agent_dir(agent_id: str) -> Path:
    normalized = str(agent_id or "").strip().replace("\\", "/").strip("/")
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    agent_dir = _agents_dir() / normalized
    if not agent_dir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent_dir


def _resolve_agent_file(agent_id: str, name: str) -> Path:
    agent_dir = _resolve_agent_dir(agent_id)
    normalized = str(name or "").strip().replace("\\", "/").strip("/")
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent file not found")
    path = agent_dir / normalized
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent file not found")
    return path


# ---------------------------------------------------------------------------
# Container-based agent operations (read/write /opt/data/profiles/)
# ---------------------------------------------------------------------------

_LIST_AGENTS_SCRIPT = r"""
import json, re, os
from pathlib import Path

NAME_RE = re.compile(r'(?:\*\*)?\s*(?:名字|name)\s*(?:：|:)\s*(?:\*\*)?\s*(.+)', re.IGNORECASE)

def parse_identity(path):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return '', ''
    name = ''
    desc = ''
    in_desc = False
    for line in lines:
        m = NAME_RE.search(line)
        if m and not name:
            name = m.group(1).strip().strip('*').strip()
        if '## 一句话简介' in line:
            in_desc = True
            continue
        if in_desc and line.strip() and not desc:
            desc = line.strip()
    return name, desc

profiles_dir = Path('/opt/data/profiles')
agents = []
if profiles_dir.exists():
    for d in sorted(profiles_dir.iterdir()):
        if not d.is_dir() or d.name.startswith('.'):
            continue
        identity = d / 'workspace' / 'IDENTITY.md'
        if not identity.exists():
            identity = d / 'IDENTITY.md'
        name, desc = parse_identity(identity)
        agents.append({
            'id': d.name,
            'name': name or d.name,
            'description': desc,
        })
print(json.dumps(agents, ensure_ascii=False))
"""


def _get_container(container_id_or_name: str):
    from app.container.manager import get_docker_container
    return get_docker_container(container_id_or_name)


def _container_name_for_user(user_id: str) -> str:
    from app.config import settings
    prefix = settings.dedicated_runtime_container_name_prefix
    return f"{prefix}-{user_id[:8]}"


def list_agents_from_container(container_id: str) -> list[dict]:
    try:
        container = _get_container(container_id)
        result = container.exec_run(["python3", "-c", _LIST_AGENTS_SCRIPT], user="hermes")
        if result.exit_code != 0:
            return []
        return json.loads(result.output.decode("utf-8"))
    except Exception:
        return []


def create_agent_in_container(container_id: str, agent_id: str) -> dict:
    container = _get_container(container_id)

    profile_dir = f"{CONTAINER_PROFILES_DIR}/{agent_id}"
    result = container.exec_run(["test", "-d", profile_dir], user="hermes")
    if result.exit_code == 0:
        raise HTTPException(status_code=409, detail=f"Agent '{agent_id}' 已存在")

    script = f"""
import os
from pathlib import Path

profile = Path('{profile_dir}')
for sub in ['memories', 'sessions', 'skills', 'skins', 'logs', 'plans', 'workspace', 'cron', 'home']:
    (profile / sub).mkdir(parents=True, exist_ok=True)

(profile / 'SOUL.md').write_text(
    '# SOUL.md - {agent_id}\\n\\n'
    '你是 {agent_id}，一个专业的 AI 助手。\\n'
    '请认真、准确地回答用户的问题。\\n',
    encoding='utf-8',
)
(profile / 'workspace' / 'IDENTITY.md').write_text(
    '# IDENTITY.md - {agent_id}\\n\\n'
    '- **名字：** {agent_id}\\n'
    '- **角色：** AI 助手\\n'
    '- **Emoji：** 🤖\\n\\n'
    '## 一句话简介\\n\\n'
    '我是 {agent_id} 智能助手。\\n',
    encoding='utf-8',
)
(profile / 'workspace' / 'AGENTS.md').write_text(
    '# AGENTS.md - {agent_id}\\n\\n'
    '本文件夹是 {agent_id} 的工作区。\\n',
    encoding='utf-8',
)
(profile / 'memories' / 'USER.md').write_text(
    '# USER.md - {agent_id}\\n\\n'
    '用户信息将在交互中逐步更新。\\n',
    encoding='utf-8',
)
print('ok')
"""
    result = container.exec_run(["python3", "-c", script], user="hermes")
    if result.exit_code != 0:
        output = result.output.decode("utf-8", errors="replace") if result.output else ""
        raise HTTPException(status_code=500, detail=f"创建 Agent 失败: {output}")

    return {"id": agent_id, "name": agent_id, "workspace": f"profiles/{agent_id}"}


def delete_agent_from_container(container_id: str, agent_id: str) -> dict:
    container = _get_container(container_id)

    profile_dir = f"{CONTAINER_PROFILES_DIR}/{agent_id}"
    result = container.exec_run(["test", "-d", profile_dir], user="hermes")
    if result.exit_code != 0:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

    result = container.exec_run(["rm", "-rf", profile_dir], user="hermes")
    if result.exit_code != 0:
        raise HTTPException(status_code=500, detail="删除 Agent 失败")

    return {"ok": True, "name": agent_id}


def list_agent_files_from_container(container_id: str, agent_id: str) -> dict:
    container = _get_container(container_id)

    script = f"""
import json
from pathlib import Path

profile = Path('{CONTAINER_PROFILES_DIR}/{agent_id}')
if not profile.is_dir():
    print(json.dumps({{"error": "not found"}}))
    exit(1)

files = []
for d in [profile, profile / 'workspace', profile / 'memories']:
    if not d.is_dir():
        continue
    for f in sorted(d.iterdir()):
        if f.is_file() and not f.name.startswith('.'):
            st = f.stat()
            files.append({{
                "name": f.name,
                "path": str(f.relative_to(profile)),
                "missing": False,
                "size": st.st_size,
                "updatedAtMs": int(st.st_mtime * 1000),
            }})
print(json.dumps({{"agentId": "{agent_id}", "workspace": "profiles/{agent_id}", "files": files}}, ensure_ascii=False))
"""
    result = container.exec_run(["python3", "-c", script], user="hermes")
    if result.exit_code != 0:
        raise HTTPException(status_code=404, detail="Agent not found")
    return json.loads(result.output.decode("utf-8"))


def get_agent_file_from_container(container_id: str, agent_id: str, name: str) -> dict:
    container = _get_container(container_id)

    safe_name = name.replace("\\", "/").strip("/")
    if ".." in safe_name or not safe_name:
        raise HTTPException(status_code=400, detail="Invalid file name")

    # Try workspace/ first, then root, then memories/
    for prefix in [f"workspace/{safe_name}", safe_name, f"memories/{safe_name}"]:
        file_path = f"{CONTAINER_PROFILES_DIR}/{agent_id}/{prefix}"
        result = container.exec_run(["cat", file_path], user="hermes")
        if result.exit_code == 0:
            return {
                "agentId": agent_id,
                "workspace": f"profiles/{agent_id}",
                "file": {
                    "name": safe_name,
                    "content": result.output.decode("utf-8"),
                },
            }

    raise HTTPException(status_code=404, detail="Agent file not found")


# ---------------------------------------------------------------------------
# Legacy local-file functions (kept for backward compat)
# ---------------------------------------------------------------------------

def list_agent_files(agent_id: str) -> dict[str, Any]:
    agent_dir = _resolve_agent_dir(agent_id)
    files = []
    for path in sorted(item for item in agent_dir.iterdir() if item.is_file() and not item.name.startswith(".")):
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "path": f"Agents/{agent_dir.name}/{path.name}",
                "missing": False,
                "size": stat.st_size,
                "updatedAtMs": int(stat.st_mtime * 1000),
            }
        )
    return {
        "agentId": agent_dir.name,
        "workspace": f"Agents/{agent_dir.name}",
        "files": files,
    }


def get_agent_file(agent_id: str, name: str) -> dict[str, Any]:
    path = _resolve_agent_file(agent_id, name)
    return {
        "agentId": path.parent.name,
        "workspace": f"Agents/{path.parent.name}",
        "file": {
            "name": path.name,
            "content": path.read_text(encoding="utf-8"),
        },
    }


def _configured_agent_ids() -> list[str]:
    defaults = _read_json(_defaults_path())
    ids = _agent_ids_from_defaults(defaults)
    for agent_id in _agent_dirs():
        if agent_id not in ids:
            ids.append(agent_id)
    return ids


def _available_model_ids(models: list[Any]) -> set[str]:
    ids: set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id:
            ids.add(model_id)
    return ids


def _fallback_agents_from_models(models: list[Any]) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        agents.append({
            "id": model_id,
            "name": model_id,
            "identity": {"name": model_id},
            "object": item.get("object", "model"),
            "available": True,
        })
    return agents


def agent_id_from_session_key(session_key: str | None) -> str | None:
    if not session_key:
        return None
    match = _SESSION_AGENT_RE.match(str(session_key))
    if not match:
        return None
    agent_id = match.group(1).strip()
    return agent_id or None


def model_for_session_key(session_key: str | None, fallback: str = DEFAULT_HERMES_MODEL) -> str:
    agent_id = agent_id_from_session_key(session_key)
    if not agent_id:
        return fallback
    return agent_id


def build_agent_info(
    models: list[Any],
    *,
    scope: str,
    runtime_mode: str,
    default_id: str | None = None,
    container_agents: list[dict] | None = None,
) -> dict[str, Any]:
    if container_agents is not None:
        agents: list[dict[str, Any]] = []
        for ca in container_agents:
            agents.append({
                "id": ca["id"],
                "name": ca.get("name") or ca["id"],
                "identity": {
                    "name": ca.get("name") or ca["id"],
                    "description": ca.get("description", ""),
                },
                "workspace": f"profiles/{ca['id']}",
                "available": True,
                "default": ca["id"] == "main",
            })
        if not agents:
            agents = _fallback_agents_from_models(models)
        resolved_default = default_id or next(
            (a["id"] for a in agents if a.get("default")), agents[0]["id"] if agents else DEFAULT_HERMES_MODEL
        )
        return {
            "agents": agents,
            "defaultId": resolved_default,
            "mainKey": f"agent:{resolved_default}",
            "scope": scope,
            "runtime_mode": runtime_mode,
        }

    configured_ids = _configured_agent_ids()
    if not configured_ids:
        agents = _fallback_agents_from_models(models)
        resolved_default = default_id or (agents[0]["id"] if agents else DEFAULT_HERMES_MODEL)
        return {
            "agents": agents,
            "defaultId": resolved_default,
            "mainKey": f"agent:{resolved_default}",
            "scope": scope,
            "runtime_mode": runtime_mode,
        }

    defaults = _read_json(_defaults_path())
    config_by_id = _agent_config_by_id(defaults)
    available = _available_model_ids(models)
    agents = []
    for agent_id in configured_ids:
        config = config_by_id.get(agent_id, {})
        agents.append({
            "id": agent_id,
            "name": _identity_name(agent_id),
            "identity": {
                "name": _identity_name(agent_id),
                "description": _agent_description(agent_id),
            },
            "workspace": config.get("workspace") or f"Agents/{agent_id}",
            "available": not available or agent_id in available,
            "default": bool(config.get("default")),
        })

    configured_default = next((item["id"] for item in agents if item.get("default")), agents[0]["id"])
    resolved_default = default_id if default_id in {item["id"] for item in agents} else configured_default
    return {
        "agents": agents,
        "defaultId": resolved_default,
        "mainKey": f"agent:{resolved_default}",
        "scope": scope,
        "runtime_mode": runtime_mode,
    }
