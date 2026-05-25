from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

DEFAULT_HERMES_MODEL = "hermes-agent"

_SESSION_AGENT_RE = re.compile(r"^agent:([^:]+):")
_IDENTITY_NAME_RE = re.compile(r"(?:\*\*)?\s*(?:名字|name)\s*(?:：|:)\s*(?:\*\*)?\s*(.+)", re.IGNORECASE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _deploy_copy_dir() -> Path:
    return _repo_root() / "deploy_copy"


def _defaults_path() -> Path:
    return _deploy_copy_dir() / "openclaw_defaults.json"


def _agents_dir() -> Path:
    return _deploy_copy_dir() / "Agents"


def _agent_dir(agent_id: str) -> Path:
    root = _agents_dir().resolve()
    path = (root / agent_id).resolve()
    if root not in path.parents or not path.is_dir():
        raise HTTPException(status_code=404, detail="Agent not found")
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Agent not found")
    return path


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


def list_agent_files(agent_id: str) -> dict[str, Any]:
    agent_dir = _agent_dir(agent_id)
    files: list[dict[str, Any]] = []
    for path in sorted(agent_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        files.append({
            "name": path.name,
            "path": path.name,
            "missing": False,
            "size": stat.st_size,
            "updatedAtMs": int(stat.st_mtime * 1000),
        })
    return {
        "agentId": agent_id,
        "workspace": f"Agents/{agent_id}",
        "files": files,
    }


def get_agent_file(agent_id: str, name: str) -> dict[str, Any]:
    agent_dir = _agent_dir(agent_id)
    path = (agent_dir / name).resolve()
    if agent_dir not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Agent file not found")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="Agent file is not UTF-8 text") from exc
    return {
        "agentId": agent_id,
        "workspace": f"Agents/{agent_id}",
        "file": {"name": path.name, "content": content},
    }


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
) -> dict[str, Any]:
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
    agents: list[dict[str, Any]] = []
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
