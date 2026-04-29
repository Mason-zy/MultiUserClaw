from __future__ import annotations

import json

from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import HTTPException, status

from app.container.manager import get_docker_container

HERMES_SKILLS_ROOT = "/opt/data/skills"

_LIST_SKILLS_SCRIPT = r"""
import json
from pathlib import Path

root = Path("/opt/data/skills")


def clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"name", "description"}:
            result[key] = clean_scalar(value)
    return result


skills = []
if root.exists():
    for skill_file in sorted(root.rglob("SKILL.md")):
        meta = frontmatter(skill_file)
        rel = skill_file.relative_to(root)
        fallback_name = skill_file.parent.name
        name = meta.get("name") or fallback_name
        skills.append(
            {
                "name": name,
                "description": meta.get("description", ""),
                "source": "hermes",
                "disabled": False,
                "path": str(rel.parent),
            }
        )

print(json.dumps(skills, ensure_ascii=False))
"""


def _exec_output(result) -> tuple[int, bytes]:
    if isinstance(result, tuple):
        exit_code, output = result
    else:
        exit_code = getattr(result, "exit_code", 0)
        output = getattr(result, "output", b"")
    if isinstance(output, str):
        output = output.encode("utf-8")
    return int(exit_code or 0), output or b""


def list_skills_from_hermes_container(container_id_or_name: str | None) -> list[dict]:
    if not container_id_or_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        )

    try:
        container = get_docker_container(container_id_or_name)
        result = container.exec_run(["python3", "-c", _LIST_SKILLS_SCRIPT])
    except DockerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        ) from exc
    except DockerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list Hermes skills",
        ) from exc

    exit_code, output = _exec_output(result)
    if exit_code != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list Hermes skills",
        )

    try:
        payload = json.loads(output.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected Hermes skills response",
        ) from exc

    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict) and item.get("name")]
